"""
Policy catalog — the single source of truth for what kinds of policy
this system can actually enforce.

Why a catalog?
--------------
Admins (via the dashboard, including the natural-language authoring box)
must not be able to invent policy *semantics* the engine has no code to
enforce. They can tune the numbers and toggle policies on/off, but every
policy must map to one of the canonical types declared here. This keeps
the system fail-closed: a NL request the parser can't map to a known
type is rejected instead of silently doing nothing.

Each entry binds:
  - a stable `policy_type` key (also used as the engine's matched_policy
    name, so it lines up with the audit log),
  - the `tool_name` the policy guards,
  - presentation metadata (label / unit) for the dashboard,
  - a built-in `default` threshold used when the DB has not been seeded
    yet (preserves the original hardcoded behaviour),
  - `value_kind` so the API/UI can coerce + validate the number.
"""

from typing import Optional


# policy_type -> spec
POLICY_TYPES: dict[str, dict] = {
    "max_delete_count": {
        "tool_name": "delete_customer",
        "label": "Maximum customers deletable per request",
        "unit": "records",
        "value_kind": "int",      # whole number >= 1
        "default": 1,
        "help": (
            "Block any delete_customer call that targets more than this "
            "many records (or whose scope is unclear)."
        ),
    },
    "max_credit_limit_raise_percent": {
        "tool_name": "update_credit_limit",
        "label": "Maximum credit-limit raise percentage",
        "unit": "%",
        "value_kind": "percent",  # number >= 0
        "default": 20.0,
        "help": (
            "Block any update_credit_limit call that raises a credit limit "
            "by more than this percentage above its current value."
        ),
    },
    "max_starting_credit_limit": {
        "tool_name": "add_customer",
        "label": "Maximum starting credit limit for a new customer",
        "unit": "",
        "value_kind": "amount",   # absolute amount >= 0
        "default": 10000.0,
        "help": (
            "Block any add_customer call whose starting credit limit exceeds "
            "this amount."
        ),
    },
}


def is_known_type(policy_type: str) -> bool:
    return policy_type in POLICY_TYPES


def tool_for_type(policy_type: str) -> Optional[str]:
    spec = POLICY_TYPES.get(policy_type)
    return spec["tool_name"] if spec else None


def default_threshold(policy_type: str) -> Optional[float]:
    spec = POLICY_TYPES.get(policy_type)
    return float(spec["default"]) if spec else None


def coerce_threshold(policy_type: str, value) -> float:
    """
    Validate + coerce a numeric threshold for the given policy type.
    Raises ValueError on anything the engine couldn't sensibly enforce.
    """
    spec = POLICY_TYPES.get(policy_type)
    if spec is None:
        raise ValueError(f"Unknown policy type '{policy_type}'.")

    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError("Threshold must be a number.")

    if spec["value_kind"] == "int":
        if num < 1:
            raise ValueError("Count threshold must be at least 1.")
        if num != int(num):
            raise ValueError("Count threshold must be a whole number.")
        return float(int(num))

    # percent
    if num < 0:
        raise ValueError("Percentage threshold cannot be negative.")
    return num