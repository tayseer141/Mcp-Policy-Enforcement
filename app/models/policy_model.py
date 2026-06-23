"""
Policy ORM model.

Business-logic policies used to be hardcoded constants inside the policy
engine (max_delete_count=1, max_raise_percent=20.0). They are now rows in
this table so an admin can create, tune, enable/disable and delete them
from the dashboard at runtime — including via the natural-language
authoring flow.

Each row maps to exactly one canonical policy type from
app.policy.catalog. The engine reads the active threshold for a tool on
every request, so changes take effect immediately with no redeploy.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String

from app.db.base import Base


class Policy(Base):
    __tablename__ = "policies"

    id = Column(Integer, primary_key=True, index=True)

    # Human/stable name. Defaults to the policy_type but can be a friendlier
    # label; used as matched_policy in audit decisions.
    name = Column(String, unique=True, nullable=False)

    # Canonical type key from app.policy.catalog.POLICY_TYPES. The engine
    # switches on this to know how to enforce the policy.
    policy_type = Column(String, nullable=False, index=True)

    # The tool this policy guards (denormalised from the catalog for easy
    # querying / display).
    tool_name = Column(String, nullable=False, index=True)

    # The numeric knob (max count, max percent, ...). Stored as float;
    # int-kind policies are coerced to whole numbers by the catalog.
    threshold = Column(Float, nullable=False)

    # Admins can switch a policy off without deleting it. A disabled policy
    # is not enforced by the engine.
    enabled = Column(Boolean, nullable=False, default=True)

    description = Column(String, nullable=False, default="")

    # Provenance / audit trail for the policy itself.
    created_by = Column(String, nullable=False, default="")
    origin = Column(String, nullable=False, default="manual")  # manual | nl | seed
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)