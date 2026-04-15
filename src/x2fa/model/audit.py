from datetime import datetime, timezone

from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.sqltypes import String, Integer, DateTime

from x2fa.model.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    action = Column(
        String(50), nullable=False, index=True
    )  # setup / verify / fail
    method = Column(
        String(50), nullable=False
    )  # webauthn_platform / webauthn_roaming / totp / backup
    ip_hash = Column(
        String(64), nullable=False
    )  # SHA256(ip + secret) — no plaintext stored
    timestamp = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
