"""Backup-Code-Verifikation."""

import time
from collections import defaultdict

from flask import (
    Blueprint, abort, g, redirect, render_template,
    request, session, url_for,
)

from app.extensions import db, limiter
from app.models import BackupCode
from app.routes import ACTION_FAIL, ACTION_VERIFY, METHOD_BACKUP, audit_log, client_ip

backup_bp = Blueprint("backup", __name__)

# In-Memory Rate-Limit (IP-Hash → [timestamps])
_backup_attempts: dict[str, list[float]] = defaultdict(list)


def _rate_limit_ok(ip_hash: str, max_attempts: int = 3, window: int = 60) -> bool:
    now = time.monotonic()
    attempts = [t for t in _backup_attempts[ip_hash] if now - t < window]
    if len(attempts) >= max_attempts:
        _backup_attempts[ip_hash] = attempts
        return False
    attempts.append(now)
    _backup_attempts[ip_hash] = attempts
    return True


def _require_session():
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(400, "Keine aktive Sitzung. Bitte starte den Login-Prozess neu.")


# ---------------------------------------------------------------------------
# GET /backup/verify
# ---------------------------------------------------------------------------

@backup_bp.route("/backup/verify")
def backup_verify_get():
    _require_session()
    return render_template(
        "backup_verify.html",
        error=request.args.get("error", ""),
        nonce=g.nonce,
    )


# ---------------------------------------------------------------------------
# POST /backup/verify
# ---------------------------------------------------------------------------

@backup_bp.route("/backup/verify", methods=["POST"])
def backup_verify_post():
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(400, "Keine aktive Sitzung.")

    user_id = session["user_id"]
    code = request.form.get("code", "").strip().upper()

    import hashlib
    from flask import current_app
    ip = client_ip()
    salt = current_app.config.get("X2FA_SECRET", "")
    ip_hash = hashlib.sha256((ip + salt).encode()).hexdigest()

    if not _rate_limit_ok(ip_hash):
        audit_log(ACTION_FAIL, METHOD_BACKUP, user_id)
        return redirect(url_for(
            "backup.backup_verify_get",
            error="Zu viele Versuche. Bitte 1 Minute warten."
        ))

    valid_codes = (
        BackupCode.query
        .filter_by(user_id=user_id)
        .filter(BackupCode.used_at.is_(None))
        .all()
    )

    from app.services.crypto import CryptoService
    matched_hash = None
    for record in valid_codes:
        if CryptoService.verify_backup_code(code, record.code_hash):
            matched_hash = record.code_hash
            break

    if matched_hash is None:
        audit_log(ACTION_FAIL, METHOD_BACKUP, user_id)
        return redirect(url_for("backup.backup_verify_get", error="Ungültiger Backup-Code."))

    # Code als verbraucht markieren
    from datetime import datetime, timezone
    record = BackupCode.query.get(matched_hash)
    record.used_at = datetime.now(timezone.utc)
    db.session.commit()

    audit_log(ACTION_VERIFY, METHOD_BACKUP, user_id)

    session["2fa_verified"] = True
    from app.routes.auth import _authorize_continue_url
    return redirect(_authorize_continue_url())
