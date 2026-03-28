"""Audit-Logging-Hilfsfunktionen für X2FA."""

import hashlib

from repositories import AuditRepo

# Event-Konstanten
FIDO2_SETUP_OK       = "fido2_setup_ok"
FIDO2_SETUP_FAIL     = "fido2_setup_fail"
FIDO2_VERIFY_OK      = "fido2_verify_ok"
FIDO2_VERIFY_FAIL    = "fido2_verify_fail"
TOTP_SETUP_OK        = "totp_setup_ok"
TOTP_VERIFY_OK       = "totp_verify_ok"
TOTP_VERIFY_FAIL     = "totp_verify_fail"
BACKUP_VERIFY_OK     = "backup_verify_ok"
BACKUP_VERIFY_FAIL   = "backup_verify_fail"
BACKUP_RATE_LIMITED  = "backup_rate_limited"


def hash_ip(ip: str) -> str:
    """SHA256-Hash der IP-Adresse — kein Klartext in der DB."""
    return hashlib.sha256(ip.encode()).hexdigest()


def log(event: str, user_id: str, ip: str, success: bool, detail: str | None = None) -> None:
    AuditRepo.log(
        event=event,
        user_id=user_id,
        ip_hash=hash_ip(ip),
        success=success,
        detail=detail,
    )
