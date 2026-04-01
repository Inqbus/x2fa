import hashlib

from flask import current_app, request

from app.extensions import db
from app.models import AuditLog

# Audit-Konstanten (aus alter audit.py übernommen)
ACTION_SETUP  = "setup"
ACTION_VERIFY = "verify"
ACTION_FAIL   = "fail"

METHOD_WEBAUTHN_PLATFORM = "webauthn_platform"
METHOD_WEBAUTHN_ROAMING  = "webauthn_roaming"
METHOD_TOTP              = "totp"
METHOD_BACKUP            = "backup"


def client_ip() -> str:
    return (
        request.environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.environ.get("REMOTE_ADDR", "unknown")
    )


def audit_log(action: str, method: str, user_id: str) -> None:
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
