"""
Policy store — the read path between the engine and the policies table.

Keeps all "which threshold is active right now?" logic in one place so the
engine stays focused on decision-making.

Resolution rules (fail-closed friendly):
  * A row exists and is enabled  -> enforce with that threshold.
  * A row exists but all are disabled -> admin explicitly turned the
    policy off -> do NOT enforce.
  * No row exists at all (e.g. unseeded DB) -> fall back to the catalog's
    built-in default and enforce it, preserving the original hardcoded
    behaviour.
"""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.policy.catalog import default_threshold
from app.models.policy_model import Policy


@dataclass
class ActivePolicy:
    enforce: bool
    threshold: Optional[float]
    name: Optional[str]


def resolve_active_policy(
    db: Session, policy_type: str, tool_name: str
) -> ActivePolicy:
    """Return the threshold the engine should enforce, if any."""
    rows = (
        db.query(Policy)
        .filter(Policy.policy_type == policy_type, Policy.tool_name == tool_name)
        .all()
    )

    if not rows:
        default = default_threshold(policy_type)
        if default is None:
            return ActivePolicy(enforce=False, threshold=None, name=None)
        return ActivePolicy(enforce=True, threshold=default, name=policy_type)

    enabled = [r for r in rows if r.enabled]
    if not enabled:
        # Admin has explicitly disabled this policy.
        return ActivePolicy(enforce=False, threshold=None, name=None)

    row = enabled[0]
    return ActivePolicy(enforce=True, threshold=row.threshold, name=row.name)