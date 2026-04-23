from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.base import Base


class AuditLog(Base):
    """
    Persistent record of every authorization decision made by the policy
    engine. Both allows and denies are recorded so the admin dashboard
    can show the full security story (who did what, which stage decided,
    and why).

    Notes
    -----
    * `username` is stored as a plain string rather than a FK so the log
      survives user deletion. Audit trails should never be silently
      pruned by cascade.
    * `arguments_json` is the tool argument bag serialized to JSON text.
      It is scrubbed of reserved keys (e.g. __raw_prompt__) before being
      persisted.
    * `raw_prompt` is stored separately (optional) so the dashboard can
      show the original natural-language request alongside the decision.
    """

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    username = Column(String(128), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False, index=True)

    # Security decision
    allowed = Column(Boolean, nullable=False, index=True)
    stage = Column(String(32), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    matched_policy = Column(String(128), nullable=True)

    # Context
    arguments_json = Column(Text, nullable=True)
    raw_prompt = Column(Text, nullable=True)

    def __repr__(self) -> str:
        verdict = "ALLOW" if self.allowed else "DENY"
        return (
            f"<AuditLog id={self.id} {verdict} "
            f"user={self.username} tool={self.tool_name} "
            f"stage={self.stage}>"
        )