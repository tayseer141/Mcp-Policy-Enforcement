"""
Natural-language policy authoring.

Turns an admin's plain-language sentence ("don't let anyone delete more
than 3 employees at once", "cap raises at 15%") into a *structured draft*
that maps to one of the canonical policy types in app.policy.catalog.

Design principles
-----------------
1. This module NEVER writes to the database. It only proposes a draft.
   The admin must review the parsed structured form and explicitly
   confirm it (POST /api/v1/admin/policies) before anything is saved.
   That confirm step is the whole point: free-text NL is never the live
   enforcement artifact — a typed, reviewed record is.

2. Fail-closed. If the text can't be mapped to a known policy type with a
   concrete number, we return an *invalid* draft with a clear reason
   rather than guessing.

3. LLM-first, heuristic-fallback. When an OpenAI key is configured we ask
   the model to classify into the catalog. When it isn't (offline / CI /
   no key) or the call fails, a deterministic keyword+number parser keeps
   the feature working. Both paths return the exact same draft shape.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

from app.core.config import settings
from app.policy.catalog import POLICY_TYPES, coerce_threshold, tool_for_type


@dataclass
class PolicyDraft:
    valid: bool
    source: str  # "llm" | "heuristic" | "none"
    explanation: str
    policy_type: Optional[str] = None
    tool_name: Optional[str] = None
    threshold: Optional[float] = None
    name: Optional[str] = None
    description: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------

def draft_policy_from_text(text: str) -> PolicyDraft:
    """Parse NL into a structured (unsaved) policy draft."""
    text = (text or "").strip()
    if not text:
        return PolicyDraft(
            valid=False,
            source="none",
            explanation="No text was provided to interpret.",
        )

    # Try the LLM first when configured; otherwise go straight to heuristic.
    if settings.OPENAI_API_KEY:
        draft = _draft_with_llm(text)
        if draft is not None:
            return draft

    return _draft_with_heuristic(text)


# ---------------------------------------------------------------------
# Finalisation shared by both paths
# ---------------------------------------------------------------------

def _finalise(
    policy_type: Optional[str],
    threshold,
    source: str,
    original_text: str,
) -> PolicyDraft:
    """Validate a (type, threshold) guess against the catalog."""
    if not policy_type or policy_type not in POLICY_TYPES:
        return PolicyDraft(
            valid=False,
            source=source,
            explanation=(
                "Could not match this to a policy the engine can enforce. "
                "Supported policies: a maximum number of customers deletable "
                "per request, and a maximum credit-limit-raise percentage."
            ),
        )

    try:
        value = coerce_threshold(policy_type, threshold)
    except ValueError as e:
        return PolicyDraft(
            valid=False,
            source=source,
            policy_type=policy_type,
            tool_name=tool_for_type(policy_type),
            explanation=(
                "Understood the kind of policy, but the limit was missing or "
                f"invalid: {e} Please restate it with a clear number."
            ),
        )

    spec = POLICY_TYPES[policy_type]
    unit = spec["unit"]
    if spec["value_kind"] == "int":
        pretty = f"{int(value)} {unit}"
    else:
        pretty = f"{value:g}{unit}"

    return PolicyDraft(
        valid=True,
        source=source,
        policy_type=policy_type,
        tool_name=spec["tool_name"],
        threshold=value,
        name=policy_type,
        description=(
            f"{spec['label']}: {pretty}. Authored from: \"{original_text}\""
        ),
        explanation=(
            f"Interpreted as “{spec['label']}” = {pretty}, guarding the "
            f"`{spec['tool_name']}` tool. Review and confirm to activate."
        ),
    )


# ---------------------------------------------------------------------
# Heuristic parser (deterministic, no external calls)
# ---------------------------------------------------------------------

def _first_number(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _draft_with_heuristic(text: str) -> PolicyDraft:
    low = text.lower()
    number = _first_number(low)

    delete_signal = any(w in low for w in ("delete", "remove", "deleting", "deletion"))
    percent_signal = ("%" in low) or ("percent" in low) or ("percentage" in low)
    start_signal = any(
        w in low for w in (
            "starting salary", "start salary", "starting credit", "new hire", "new hires",
            "new employee", "new employees", "new customer", "new customers",
            "hiring", "onboard", "onboarding",
            "add employee", "adding employee", "add customer", "adding customer",
        )
    )
    salary_signal = percent_signal or any(
        w in low for w in (
            "salary", "salaries", "raise", "pay", "wage", "compensation",
            "credit", "credit limit", "limit",
        )
    )

    # Starting-salary phrasing is specific to new hires; check it before the
    # generic salary branch so "cap starting salary at 8000" doesn't get
    # mistaken for a raise policy.
    if start_signal:
        return _finalise("max_starting_credit_limit", number, "heuristic", text)
    # A percentage signal is specific to the salary-raise policy.
    if salary_signal and percent_signal:
        return _finalise("max_credit_limit_raise_percent", number, "heuristic", text)
    if delete_signal:
        return _finalise("max_delete_count", number, "heuristic", text)
    if salary_signal:
        return _finalise("max_credit_limit_raise_percent", number, "heuristic", text)

    return PolicyDraft(
        valid=False,
        source="heuristic",
        explanation=(
            "Couldn't tell which policy you mean. Try phrasing it like "
            "“limit deletes to 2 customers per request”, “cap credit-limit "
            "raises at 15%”, or “new customers can't start above 9000”."
        ),
    )


# ---------------------------------------------------------------------
# LLM parser
# ---------------------------------------------------------------------

_LLM_SYSTEM = """
You convert an administrator's natural-language instruction into a single
structured security policy for a customer database system.

You may ONLY choose from these policy types:
- "max_delete_count": the maximum number of customer records that may be
  deleted in one request. threshold is a whole number >= 1.
- "max_credit_limit_raise_percent": the maximum percentage a customer's credit
  limit may be raised in one update. threshold is a number >= 0 (e.g. 15
  means 15%).
- "max_starting_credit_limit": the maximum starting credit limit allowed when
  adding a NEW customer. threshold is an absolute amount >= 0 (e.g. 9000).

Respond with a JSON object only, no prose:
{"policy_type": <one of the three strings or null>,
 "threshold": <number or null>}

If the instruction does not clearly map to one of these policies, or has
no usable number, set policy_type and/or threshold to null. Never invent a
policy type that is not listed.
""".strip()


def _draft_with_llm(text: str) -> Optional[PolicyDraft]:
    """Returns a draft, or None to signal the caller to fall back."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = (response.choices[0].message.content or "").strip()
        data = json.loads(content)
        policy_type = data.get("policy_type")
        threshold = data.get("threshold")
        return _finalise(policy_type, threshold, "llm", text)
    except Exception:
        # Any error (no network, bad key, malformed JSON) -> let the caller
        # fall back to the deterministic heuristic.
        return None