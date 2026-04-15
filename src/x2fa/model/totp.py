from datetime import datetime, timezone

from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.sqltypes import LargeBinary, String, Boolean, DateTime

from x2fa.constants import NEVER_USED
from x2fa.model.base import Base


class TOTPSecret(Base):
    __tablename__ = "totp_secret"

    user_id = Column(String(255), primary_key=True)
    secret_encrypted = Column(LargeBinary, nullable=False)
    verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_USED sentinel: set when the row is created (QR-code scanned, verified=False).
    # Replaced with the actual timestamp after the first successful code check.
    # The anti-replay check in totp_helpers.verify_code() always computes the delta;
    # NEVER_USED is far enough in the past that the 30-second window never triggers.
    last_used_at = Column(DateTime, nullable=False, default=NEVER_USED)


class BackupCode(Base):
    __tablename__ = "backup_code"

    code_hash = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    # NEVER_USED sentinel: set at creation; replaced with the redemption timestamp
    # when the code is consumed. Active codes: used_at == NEVER_USED.
    used_at = Column(DateTime, nullable=False, default=NEVER_USED)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
