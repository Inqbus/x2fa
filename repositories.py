import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from models import AuditLog, BackupCode, Challenge, Credential, SessionLocal, TOTPSecret


# ---------------------------------------------------------------------------
# CredentialRepo
# ---------------------------------------------------------------------------

class CredentialRepo:

    @staticmethod
    def save(
        credential_id: bytes,
        user_id: str,
        public_key: bytes,
        sign_count: int,
        authenticator_type: str,
        is_passkey: bool = False,
    ) -> None:
        with SessionLocal() as db:
            cred = Credential(
                credential_id=credential_id,
                user_id=user_id,
                public_key=public_key,
                sign_count=sign_count,
                authenticator_type=authenticator_type,
                is_passkey=is_passkey,
            )
            db.add(cred)
            db.commit()

    @staticmethod
    def get_by_id(credential_id: bytes) -> Optional[Credential]:
        with SessionLocal() as db:
            return db.get(Credential, credential_id)

    @staticmethod
    def list_by_user(user_id: str) -> list[Credential]:
        with SessionLocal() as db:
            return db.query(Credential).filter_by(user_id=user_id).all()

    @staticmethod
    def update_sign_count(credential_id: bytes, new_count: int) -> None:
        with SessionLocal() as db:
            cred = db.get(Credential, credential_id)
            if cred:
                cred.sign_count = new_count
                cred.last_used_at = datetime.now(tz=timezone.utc)
                db.commit()

    @staticmethod
    def delete(credential_id: bytes) -> None:
        with SessionLocal() as db:
            cred = db.get(Credential, credential_id)
            if cred:
                db.delete(cred)
                db.commit()


# ---------------------------------------------------------------------------
# ChallengeRepo
# ---------------------------------------------------------------------------

class ChallengeRepo:

    @staticmethod
    def create(user_id: str, challenge: bytes, ttl_minutes: int = 5) -> str:
        challenge_id = str(uuid.uuid4())
        expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=ttl_minutes)
        with SessionLocal() as db:
            db.add(Challenge(
                challenge_id=challenge_id,
                user_id=user_id,
                challenge=challenge,
                expires_at=expires_at,
            ))
            db.commit()
        return challenge_id

    @staticmethod
    def consume(challenge_id: str, user_id: str) -> Optional[bytes]:
        """Gibt die Challenge zurück und markiert sie als verbraucht.
        Gibt None zurück wenn nicht gefunden, bereits verbraucht oder abgelaufen."""
        with SessionLocal() as db:
            ch = db.get(Challenge, challenge_id)
            if ch is None:
                return None
            if ch.user_id != user_id:
                return None
            if ch.used:
                return None
            if ch.expires_at.replace(tzinfo=timezone.utc) < datetime.now(tz=timezone.utc):
                return None
            ch.used = True
            db.commit()
            return bytes(ch.challenge)

    @staticmethod
    def purge_expired() -> None:
        """Aufräumen abgelaufener Challenges (kann periodisch aufgerufen werden)."""
        with SessionLocal() as db:
            db.query(Challenge).filter(
                Challenge.expires_at < datetime.now(tz=timezone.utc)
            ).delete()
            db.commit()


# ---------------------------------------------------------------------------
# TOTPRepo
# ---------------------------------------------------------------------------

class TOTPRepo:

    @staticmethod
    def save(user_id: str, secret_encrypted: bytes) -> None:
        with SessionLocal() as db:
            existing = db.get(TOTPSecret, user_id)
            if existing:
                existing.secret_encrypted = secret_encrypted
                existing.verified = False
                existing.last_used_at = None
            else:
                db.add(TOTPSecret(
                    user_id=user_id,
                    secret_encrypted=secret_encrypted,
                ))
            db.commit()

    @staticmethod
    def get(user_id: str) -> Optional[TOTPSecret]:
        with SessionLocal() as db:
            return db.get(TOTPSecret, user_id)

    @staticmethod
    def set_verified(user_id: str) -> None:
        with SessionLocal() as db:
            secret = db.get(TOTPSecret, user_id)
            if secret:
                secret.verified = True
                db.commit()

    @staticmethod
    def update_last_used(user_id: str) -> None:
        with SessionLocal() as db:
            secret = db.get(TOTPSecret, user_id)
            if secret:
                secret.last_used_at = datetime.now(tz=timezone.utc)
                db.commit()

    @staticmethod
    def delete(user_id: str) -> None:
        with SessionLocal() as db:
            secret = db.get(TOTPSecret, user_id)
            if secret:
                db.delete(secret)
                db.commit()


# ---------------------------------------------------------------------------
# BackupRepo
# ---------------------------------------------------------------------------

class BackupRepo:

    @staticmethod
    def save_many(user_id: str, code_hashes: list[str]) -> None:
        with SessionLocal() as db:
            for code_hash in code_hashes:
                db.add(BackupCode(code_hash=code_hash, user_id=user_id))
            db.commit()

    @staticmethod
    def find_valid(user_id: str) -> list[BackupCode]:
        with SessionLocal() as db:
            return (
                db.query(BackupCode)
                .filter_by(user_id=user_id)
                .filter(BackupCode.used_at.is_(None))
                .all()
            )

    @staticmethod
    def consume(code_hash: str, user_id: str) -> bool:
        """Markiert den Code als verbraucht. Gibt True zurück bei Erfolg."""
        with SessionLocal() as db:
            code = (
                db.query(BackupCode)
                .filter_by(code_hash=code_hash, user_id=user_id)
                .filter(BackupCode.used_at.is_(None))
                .first()
            )
            if code is None:
                return False
            code.used_at = datetime.now(tz=timezone.utc)
            db.commit()
            return True

    @staticmethod
    def count_valid(user_id: str) -> int:
        with SessionLocal() as db:
            return (
                db.query(BackupCode)
                .filter_by(user_id=user_id)
                .filter(BackupCode.used_at.is_(None))
                .count()
            )

    @staticmethod
    def delete_all(user_id: str) -> None:
        with SessionLocal() as db:
            db.query(BackupCode).filter_by(user_id=user_id).delete()
            db.commit()


# ---------------------------------------------------------------------------
# AuditRepo
# ---------------------------------------------------------------------------

class AuditRepo:

    @staticmethod
    def log(
        event: str,
        user_id: str,
        ip_hash: str,
        success: bool,
        detail: str | None = None,
    ) -> None:
        with SessionLocal() as db:
            db.add(AuditLog(
                event=event,
                user_id=user_id,
                ip_hash=ip_hash,
                success=success,
                detail=detail,
            ))
            db.commit()

    @staticmethod
    def list_by_user(user_id: str, limit: int = 50) -> list[AuditLog]:
        with SessionLocal() as db:
            return (
                db.query(AuditLog)
                .filter_by(user_id=user_id)
                .order_by(AuditLog.created_at.desc())
                .limit(limit)
                .all()
            )

    @staticmethod
    def stats() -> dict:
        with SessionLocal() as db:
            from sqlalchemy import func
            rows = (
                db.query(AuditLog.event, AuditLog.success, func.count())
                .group_by(AuditLog.event, AuditLog.success)
                .all()
            )
            result = {}
            for event, success, count in rows:
                key = f"{event}.{'ok' if success else 'fail'}"
                result[key] = count
            return result
