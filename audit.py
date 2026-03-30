"""Audit-Logging-Hilfsfunktionen für X2FA."""

import hashlib

from repositories import AuditRepo

# Action-Konstanten
ACTION_SETUP  = "setup"
ACTION_VERIFY = "verify"
ACTION_FAIL   = "fail"

# Method-Konstanten
METHOD_WEBAUTHN_PLATFORM = "webauthn_platform"
METHOD_WEBAUTHN_ROAMING  = "webauthn_roaming"
METHOD_TOTP              = "totp"
METHOD_BACKUP            = "backup"

_SECRET_SALT: str = ""


def init_audit(secret: str) -> None:
    global _SECRET_SALT
    _SECRET_SALT = secret


def hash_ip(ip: str) -> str:
    """SHA256(ip + SECRET_SALT) — kein Klartext in der DB (DSGVO-konform)."""
    return hashlib.sha256((ip + _SECRET_SALT).encode()).hexdigest()


def log(action: str, method: str, user_id: str, ip: str) -> None:
    AuditRepo.log(
        action=action,
        method=method,
        user_id=user_id,
        ip_hash=hash_ip(ip),
    )
