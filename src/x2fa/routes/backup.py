"""Backup code verification."""

from http import HTTPStatus

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babelplus import gettext as _

from x2fa.init_app.limiter import limiter
from x2fa.models import BackupCode
from x2fa.constants import ACTION_FAIL, ACTION_VERIFY, METHOD_BACKUP, NEVER_USED
from x2fa.routes import audit_log

backup_bp = Blueprint("backup", __name__)


def _require_session():
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(
            HTTPStatus.BAD_REQUEST,
            _("No active session. Please restart the login process."),
        )


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
@limiter.limit(lambda: current_app.config.x2fa_ratelimit.RATE_LIMIT_BACKUP_VERIFY)
def backup_verify_post():
    _require_session()
    user_id = session["user_id"]
    code = request.form.get("code", "").strip().upper()

    valid_codes = (
        BackupCode.query.filter_by(user_id=user_id)
        .filter(BackupCode.used_at == NEVER_USED)
        .all()
    )

    from x2fa.services.crypto import CryptoService

    matched_hash = None
    for record in valid_codes:
        if CryptoService.verify_backup_code(code, record.code_hash):
            matched_hash = record.code_hash
            break

    if matched_hash is None:
        audit_log(ACTION_FAIL, METHOD_BACKUP, user_id)
        return redirect(
            url_for("backup.backup_verify_get", error=_("Invalid backup code."))
        )

    # Mark code as used
    from datetime import datetime, timezone

    record = g.db_session.get(BackupCode, matched_hash)
    record.used_at = datetime.now(timezone.utc)
    g.db_session.commit()

    audit_log(ACTION_VERIFY, METHOD_BACKUP, user_id)

    session["2fa_verified"] = True
    from x2fa.routes.auth import _authorize_continue_url

    return redirect(_authorize_continue_url())
