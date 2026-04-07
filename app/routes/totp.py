"""TOTP routes: setup and verification."""

from datetime import datetime, timezone
from http import HTTPStatus

import totp_helpers
from flask import (
    Blueprint, abort, current_app, g, redirect, render_template,
    request, session, url_for,
)
from flask_babel import gettext as _

from app.extensions import db, limiter
from app.models import BackupCode, TOTPSecret
from app.constants import ACTION_FAIL, ACTION_SETUP, ACTION_VERIFY, BACKUP_CODES_COUNT, METHOD_TOTP, NEVER_USED
from app.routes import audit_log
from app.services.crypto import CryptoService

totp_bp = Blueprint("totp", __name__)


def _require_session():
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(HTTPStatus.BAD_REQUEST, _("No active session. Please restart the login process."))


# ---------------------------------------------------------------------------
# GET /totp/setup
# ---------------------------------------------------------------------------

@totp_bp.route("/totp/setup")
def totp_setup_get():
    _require_session()
    user_id = session["user_id"]

    secret = totp_helpers.generate_secret()
    crypto = CryptoService(current_app.config["X2FA_SECRET"])

    secret_encrypted = crypto.encrypt(secret)
    provisioning_uri = totp_helpers.build_provisioning_uri(
        secret, user_id, issuer=current_app.config["X2FA_DOMAIN"]
    )

    # Persist (unverified until the code is confirmed)
    existing = db.session.get(TOTPSecret, user_id)
    if existing:
        existing.secret_encrypted = secret_encrypted
        existing.verified = False
        existing.last_used_at = None
    else:
        db.session.add(TOTPSecret(
            user_id=user_id,
            secret_encrypted=secret_encrypted,
        ))
    db.session.commit()

    return render_template(
        "totp_setup.html",
        secret=secret,
        qr_data_uri=totp_helpers.generate_qr_data_uri(provisioning_uri),
        error=request.args.get("error", ""),
        nonce=g.nonce,
    )


# ---------------------------------------------------------------------------
# POST /totp/setup/verify
# ---------------------------------------------------------------------------

@totp_bp.route("/totp/setup/verify", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATE_LIMIT_TOTP_SETUP"])
def totp_setup_verify():
    _require_session()
    user_id = session["user_id"]
    code = request.form.get("code", "").strip()

    totp_record = db.session.get(TOTPSecret, user_id)
    if totp_record is None:
        abort(HTTPStatus.BAD_REQUEST, _("No TOTP secret found. Please restart setup."))

    secret = CryptoService(current_app.config["X2FA_SECRET"]).decrypt(
        bytes(totp_record.secret_encrypted)
    )

    if not totp_helpers.verify_code(secret, code, last_used_at=NEVER_USED):
        audit_log(ACTION_FAIL, METHOD_TOTP, user_id)
        return redirect(url_for("totp.totp_setup_get", error=_("Wrong code. Please try again.")))

    totp_record.verified = True
    totp_record.last_used_at = datetime.now(timezone.utc)

    # Generate backup codes (same as WebAuthn setup flow)
    codes = CryptoService.generate_backup_codes(BACKUP_CODES_COUNT)
    for code_hash in [CryptoService.hash_backup_code(c) for c in codes]:
        db.session.add(BackupCode(code_hash=code_hash, user_id=user_id))

    db.session.commit()
    audit_log(ACTION_SETUP, METHOD_TOTP, user_id)

    session["backup_codes"] = codes
    session["2fa_verified"] = True
    return redirect(url_for("setup.setup_done"))


# ---------------------------------------------------------------------------
# GET /totp/verify
# ---------------------------------------------------------------------------

@totp_bp.route("/totp/verify")
def totp_verify_get():
    _require_session()
    user_id = session["user_id"]

    totp_record = db.session.get(TOTPSecret, user_id)
    if totp_record is None or not totp_record.verified:
        from app.routes.auth import _oidc_error_redirect
        return _oidc_error_redirect("access_denied")

    return render_template(
        "totp_verify.html",
        error=request.args.get("error", ""),
        nonce=g.nonce,
    )


# ---------------------------------------------------------------------------
# POST /totp/verify
# ---------------------------------------------------------------------------

@totp_bp.route("/totp/verify", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATE_LIMIT_TOTP_VERIFY"])
def totp_verify_post():
    _require_session()
    user_id = session["user_id"]
    code = request.form.get("code", "").strip()

    totp_record = db.session.get(TOTPSecret, user_id)
    if totp_record is None or not totp_record.verified:
        # Treat missing TOTP identically to a wrong code — no state leak
        audit_log(ACTION_FAIL, METHOD_TOTP, user_id)
        return redirect(url_for(
            "totp.totp_verify_get",
            error=_("Wrong or already used code.")
        ))

    secret = CryptoService(current_app.config["X2FA_SECRET"]).decrypt(
        bytes(totp_record.secret_encrypted)
    )

    if not totp_helpers.verify_code(secret, code, last_used_at=totp_record.last_used_at):
        audit_log(ACTION_FAIL, METHOD_TOTP, user_id)
        return redirect(url_for(
            "totp.totp_verify_get",
            error=_("Wrong or already used code.")
        ))

    totp_record.last_used_at = datetime.now(timezone.utc)
    db.session.commit()
    audit_log(ACTION_VERIFY, METHOD_TOTP, user_id)

    session["2fa_verified"] = True
    from app.routes.auth import _authorize_continue_url
    return redirect(_authorize_continue_url())
