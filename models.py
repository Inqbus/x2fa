import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, LargeBinary, String, Text, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get("X2FA_DATABASE_URL", "sqlite:///x2fa.db")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Credential(Base):
    __tablename__ = "credentials"

    credential_id = Column(LargeBinary, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    authenticator_type = Column(String(20), nullable=False)  # platform/roaming/hybrid
    is_passkey = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


class Challenge(Base):
    __tablename__ = "challenges"

    challenge_id = Column(String(255), primary_key=True)  # UUID
    user_id = Column(String(255), nullable=False, index=True)
    challenge = Column(LargeBinary, nullable=False)  # 32-64 Bytes
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, nullable=False, default=False)


class TOTPSecret(Base):
    __tablename__ = "totp_secrets"

    user_id = Column(String(255), primary_key=True)
    secret_encrypted = Column(LargeBinary, nullable=False)
    verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)


class BackupCode(Base):
    __tablename__ = "backup_codes"

    code_hash = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)  # NULL = gültig
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event = Column(String(64), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    ip_hash = Column(String(64), nullable=False)   # SHA256 der IP, kein Klartext
    success = Column(Boolean, nullable=False)
    detail = Column(Text, nullable=True)           # Optionale Zusatzinfo (kein PII)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


def init_db():
    Base.metadata.create_all(bind=engine)
