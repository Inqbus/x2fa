import hashlib

from flask import current_app, request

from app.extensions import db
from app.models import AuditLog

# Audit action constants
ACTION_SETUP  = "setup"
ACTION_VERIFY = "verify"
ACTION_FAIL   = "fail"

# Audit method constants
METHOD_WEBAUTHN_PLATFORM = "webauthn_platform"
METHOD_WEBAUTHN_ROAMING  = "webauthn_roaming"
METHOD_TOTP              = "totp"
METHOD_BACKUP            = "backup"


def client_ip() -> str:
    """Returns the real client IP, preferring X-Forwarded-For behind a reverse proxy."""
    return (
        request.environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.environ.get("REMOTE_ADDR", "unknown")
    )


def audit_log(action: str, method: str, user_id: str) -> None:
    """
    Writes a pseudonymous audit record.

    The IP address is stored as SHA256(ip + X2FA_SECRET), never in plaintext.
    This satisfies GDPR pseudonymisation requirements.
    """
    ip = client_ip()
    salt = current_app.config.get("X2FA_SECRET", "")
    ip_hash = hashlib.sha256((ip + salt).encode()).hexdigest()
    db.session.add(AuditLog(
        action=action,
        method=method,
        user_id=user_id,
        ip_hash=ip_hash,
    ))
    db.session.commit()
