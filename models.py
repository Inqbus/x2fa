import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Index, Integer, LargeBinary, String, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("X2FA_DATABASE_URL", "sqlite:///x2fa.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Credential(Base):
    __tablename__ = "credentials"

    credential_id    = Column(LargeBinary,    primary_key=True)
    user_id          = Column(String(255),    nullable=False, index=True)
    public_key       = Column(LargeBinary,    nullable=False)
    sign_count       = Column(Integer,        nullable=False, default=0)
    authenticator_type = Column(String(20),   nullable=False)   # platform / roaming / hybrid
    device_type      = Column(String(20),     nullable=False, default="single_device")  # single_device / multi_device
    transport        = Column(String(50),     nullable=True)    # usb / nfc / ble / hybrid / internal
    is_passkey       = Column(Boolean,        nullable=False, default=False)
    created_at       = Column(DateTime,       nullable=False, default=datetime.utcnow)
    last_used_at     = Column(DateTime,       nullable=True)

    __table_args__ = (
        Index("idx_cred_user_created", "user_id", "created_at"),
    )


class Challenge(Base):
    __tablename__ = "challenges"

    challenge_id = Column(String(255),  primary_key=True)
    user_id      = Column(String(255),  nullable=False, index=True)
    challenge    = Column(LargeBinary,  nullable=False)
    expires_at   = Column(DateTime,     nullable=False, index=True)
    used         = Column(Boolean,      nullable=False, default=False)


class TOTPSecret(Base):
    __tablename__ = "totp_secrets"

    user_id          = Column(String(255),  primary_key=True)
    secret_encrypted = Column(LargeBinary,  nullable=False)
    verified         = Column(Boolean,      nullable=False, default=False)
    created_at       = Column(DateTime,     nullable=False, default=datetime.utcnow)
    last_used_at     = Column(DateTime,     nullable=True)


class BackupCode(Base):
    __tablename__ = "backup_codes"

    code_hash  = Column(String(255),  primary_key=True)
    user_id    = Column(String(255),  nullable=False, index=True)
    used_at    = Column(DateTime,     nullable=True)
    created_at = Column(DateTime,     nullable=False, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id        = Column(Integer,      primary_key=True, autoincrement=True)
    user_id   = Column(String(255),  nullable=False, index=True)
    action    = Column(String(50),   nullable=False, index=True)  # setup / verify / fail
    method    = Column(String(50),   nullable=False)              # webauthn_platform / webauthn_roaming / totp / backup
    ip_hash   = Column(String(64),   nullable=False)              # SHA256(ip + salt), kein Klartext
    timestamp = Column(DateTime,     nullable=False, default=datetime.utcnow, index=True)


def init_db():
    Base.metadata.create_all(bind=engine)
