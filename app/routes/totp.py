"""TOTP routes: setup and verification."""

from http import HTTPStatus

from flask import (
    Blueprint, abort, g, redirect, render_template,
    request, session, url_for,
)
from flask_babel import gettext as _

from app.extensions import db, limiter
from app.models import TOTPSecret
from app.routes import ACTION_FAIL, ACTION_SETUP, ACTION_VERIFY, METHOD_TOTP, audit_log

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

    import totp_helpers
    from app.services.crypto import CryptoService
    from flask import current_app

    secret = totp_helpers.generate_secret()
    domain = current_app.config["X2FA_DOMAIN"]
    crypto = CryptoService(current_app.config["X2FA_SECRET"])

    secret_encrypted = crypto.encrypt(secret)
    provisioning_uri = totp_helpers.build_provisioning_uri(secret, user_id, issuer=domain)
    qr_data_uri = totp_helpers.generate_qr_data_uri(provisioning_uri)

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
        qr_data_uri=qr_data_uri,
        error=request.args.get("error", ""),
        nonce=g.nonce,
    )


# ---------------------------------------------------------------------------
# POST /totp/setup/verify
# ---------------------------------------------------------------------------

@totp_bp.route("/totp/setup/verify", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def totp_setup_verify():
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(HTTPStatus.BAD_REQUEST, _("No active session."))

    user_id = session["user_id"]
    code = request.form.get("code", "").strip()

    totp_record = db.session.get(TOTPSecret, user_id)
    if totp_record is None:
        abort(HTTPStatus.BAD_REQUEST, _("No TOTP secret found. Please restart setup."))

    from app.services.crypto import CryptoService
    from flask import current_app
    import totp_helpers

    crypto = CryptoService(current_app.config["X2FA_SECRET"])
    secret = crypto.decrypt(bytes(totp_record.secret_encrypted))

    if not totp_helpers.verify_code(secret, code):
        audit_log(ACTION_FAIL, METHOD_TOTP, user_id)
        return redirect(url_for("totp.totp_setup_get", error=_("Wrong code. Please try again.")))

    totp_record.verified = True
    db.session.commit()
    audit_log(ACTION_SETUP, METHOD_TOTP, user_id)

    # 2FA successful — redirect back to /authorize
    session["2fa_verified"] = True
    from app.routes.auth import _authorize_continue_url
    return redirect(_authorize_continue_url())


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
@limiter.limit("5 per minute; 20 per hour")
def totp_verify_post():
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(HTTPStatus.BAD_REQUEST, _("No active session."))

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

    from app.services.crypto import CryptoService
    from flask import current_app
    import totp_helpers

    crypto = CryptoService(current_app.config["X2FA_SECRET"])
    secret = crypto.decrypt(bytes(totp_record.secret_encrypted))

    if not totp_helpers.verify_code(secret, code, last_used_at=totp_record.last_used_at):
        audit_log(ACTION_FAIL, METHOD_TOTP, user_id)
        return redirect(url_for(
            "totp.totp_verify_get",
            error=_("Wrong or already used code.")
        ))

    from datetime import datetime, timezone
    totp_record.last_used_at = datetime.now(timezone.utc)
    db.session.commit()
    audit_log(ACTION_VERIFY, METHOD_TOTP, user_id)

    session["2fa_verified"] = True
    from app.routes.auth import _authorize_continue_url
    return redirect(_authorize_continue_url())
