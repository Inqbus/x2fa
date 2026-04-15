from datetime import datetime, timezone

from sqlalchemy.sql.schema import Column, Index
from sqlalchemy.sql.sqltypes import LargeBinary, String, Integer, Boolean, DateTime

from x2fa.constants import NEVER_USED
from x2fa.model.base import Base


class Credential(Base):
    __tablename__ = "credential"

    credential_id = Column(LargeBinary, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    authenticator_type = Column(String(20), nullable=False)  # platform / roaming
    device_type = Column(
        String(20), nullable=False, default="single_device"
    )  # single_device / multi_device
    # WebAuthn spec §5.8.4: transport hints are OPTIONAL. Platform authenticators
    # (Touch ID, Windows Hello, Android biometrics) communicate internally and have
    # no physical transport to report. Empty string = "not reported by authenticator".
    transport = Column(
        String(50), nullable=False, default=""
    )  # usb / nfc / ble / hybrid / internal / "" = unknown
    is_passkey = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_USED sentinel: set at registration; replaced on first successful assertion.
    last_used_at = Column(DateTime, nullable=False, default=NEVER_USED)

    __table_args__ = (Index("idx_cred_user_created", "user_id", "created_at"),)


class Challenge(Base):
    """Short-lived WebAuthn challenge (TTL 5 minutes, single-use)."""

    __tablename__ = "challenge"

    challenge_id = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    challenge = Column(LargeBinary, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, nullable=False, default=False)
