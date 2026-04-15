"""WebAuthn assertion (verification) routes."""

import json
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from http import HTTPStatus

from flask import (
    Blueprint,
    abort,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babelplus import gettext as _

from sqlalchemy import select

from x2fa.helpers import webauthn_helpers
from x2fa.init_app.limiter import limiter
from x2fa.model import Challenge, Credential
from x2fa.constants import (
    ACTION_FAIL,
    ACTION_VERIFY,
    CHALLENGE_BYTES,
    METHOD_WEBAUTHN_PLATFORM,
    METHOD_WEBAUTHN_ROAMING,
)
from x2fa.routes import audit_log

verify_bp = Blueprint("verify", __name__)


def _require_session():
    """Aborts with 400 if no active OIDC session is present."""
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(
            HTTPStatus.BAD_REQUEST,
            _("No active session. Please restart the login process."),
        )


# ---------------------------------------------------------------------------
# GET /verify
# ---------------------------------------------------------------------------


@verify_bp.route("/verify")
def verify_get():
    _require_session()
    user_id = session["user_id"]

    stmt = select(Credential).where(Credential.user_id == user_id)
    credentials = g.db_session.execute(stmt).scalars().all()
    if not credentials:
        # No WebAuthn credentials — check for TOTP as fallback
        from x2fa.model import TOTPSecret

        totp_record = g.db_session.get(TOTPSecret, user_id)
        if totp_record and totp_record.verified:
            return redirect(url_for("totp.totp_verify_get"))
        # No 2FA method registered at all — return OIDC error to the RP
        # without revealing any user-specific state in the browser
        from x2fa.routes.auth import _oidc_error_redirect

        return _oidc_error_redirect("access_denied")

    challenge_bytes = secrets.token_bytes(CHALLENGE_BYTES)
    challenge_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config.x2fa_ratelimit.CHALLENGE_TTL_MINUTES
    )

    g.db_session.add(
        Challenge(
            challenge_id=challenge_id,
            user_id=user_id,
            challenge=challenge_bytes,
            expires_at=expires_at,
        )
    )
    g.db_session.commit()

    credential_ids = [bytes(c.credential_id) for c in credentials]
    transports_list = [
        c.transport.split(",") if c.transport else [] for c in credentials
    ]

    options_json = webauthn_helpers.build_authentication_options_json(
        challenge_bytes, credential_ids, transports=transports_list
    )

    return render_template(
        "verify.html",
        challenge_id=challenge_id,
        options_json=options_json,
        nonce=g.nonce,
    )


# ---------------------------------------------------------------------------
# POST /verify/complete
# ---------------------------------------------------------------------------


@verify_bp.route("/verify/complete", methods=["POST"])
@limiter.limit(lambda: current_app.config.x2fa_ratelimit.RATE_LIMIT_WEBAUTHN_VERIFY)
def verify_complete():
    if not session.get("oidc_request") or not session.get("user_id"):
        return jsonify({"error": _("No active session.")}), HTTPStatus.UNAUTHORIZED

    data = request.get_json()
    if not data:
        return jsonify({"error": _("Missing JSON body.")}), HTTPStatus.BAD_REQUEST

    user_id = session["user_id"]
    challenge_id = data.get("challenge_id", "")

    # Consume the challenge (single-use, TTL check)
    ch = g.db_session.get(Challenge, challenge_id)
    if not ch or ch.user_id != user_id or ch.used:
        return jsonify({"error": _("Invalid challenge.")}), HTTPStatus.BAD_REQUEST

    exp = ch.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > exp:
        return jsonify({"error": _("Challenge expired.")}), HTTPStatus.BAD_REQUEST

    ch.used = True
    g.db_session.commit()
    challenge_bytes = bytes(ch.challenge)

    # Decode rawId to look up the stored credential
    from webauthn import base64url_to_bytes

    try:
        raw_id = base64url_to_bytes(data.get("rawId", ""))
    except Exception:
        return jsonify({"error": _("Invalid credential ID.")}), HTTPStatus.BAD_REQUEST

    cred = g.db_session.get(Credential, raw_id)
    if cred is None or cred.user_id != user_id:
        return jsonify({"error": _("Credential not found.")}), HTTPStatus.NOT_FOUND

    credential_json = json.dumps(
        {
            "id": data.get("id"),
            "rawId": data.get("rawId"),
            "type": data.get("type"),
            "response": data.get("response", {}),
        }
    )

    try:
        new_sign_count = webauthn_helpers.verify_authentication(
            challenge=challenge_bytes,
            credential_json=credential_json,
            stored_public_key=bytes(cred.public_key),
            stored_sign_count=cred.sign_count,
        )
    except ValueError as exc:
        audit_log(ACTION_FAIL, METHOD_WEBAUTHN_ROAMING, user_id)
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST

    # Update sign count — regression would indicate a cloned authenticator
    cred.sign_count = new_sign_count
    cred.last_used_at = datetime.now(timezone.utc)
    g.db_session.commit()

    method = (
        METHOD_WEBAUTHN_PLATFORM
        if cred.authenticator_type == "platform"
        else METHOD_WEBAUTHN_ROAMING
    )
    audit_log(ACTION_VERIFY, method, user_id)

    # Mark 2FA as complete and redirect back to the authorization endpoint
    session["2fa_verified"] = True
    from x2fa.routes.auth import _authorize_continue_url

    return jsonify({"redirect_url": _authorize_continue_url()})
