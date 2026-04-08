"""2FA setup routes: method selection, WebAuthn registration, backup code display."""

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
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _

from app.src.x2fa.app import webauthn_helpers
from app.src.x2fa.app.extensions import db, limiter
from app.src.x2fa.app.models import BackupCode, Challenge, Credential
from app.src.x2fa.app.constants import (
    ACTION_SETUP,
    BACKUP_CODES_COUNT,
    CHALLENGE_BYTES,
    METHOD_WEBAUTHN_PLATFORM,
    METHOD_WEBAUTHN_ROAMING,
)
from app.src.x2fa.app.routes import audit_log
from app.src.x2fa.app.services.crypto import CryptoService

setup_bp = Blueprint("setup", __name__)


def _require_session():
    """Aborts with 400 if no active OIDC session is present."""
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(
            HTTPStatus.BAD_REQUEST,
            _("No active session. Please restart the login process."),
        )


# ---------------------------------------------------------------------------
# GET /setup  —  method selection screen
# ---------------------------------------------------------------------------


@setup_bp.route("/setup")
def setup_choose():
    _require_session()
    return render_template("setup_choose.html", nonce=g.nonce)


# ---------------------------------------------------------------------------
# GET /setup/webauthn  —  WebAuthn registration UI
# ---------------------------------------------------------------------------


@setup_bp.route("/setup/webauthn")
def setup_webauthn_get():
    _require_session()
    user_id = session["user_id"]

    challenge_bytes = secrets.token_bytes(CHALLENGE_BYTES)
    challenge_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config["CHALLENGE_TTL_MINUTES"]
    )

    db.session.add(
        Challenge(
            challenge_id=challenge_id,
            user_id=user_id,
            challenge=challenge_bytes,
            expires_at=expires_at,
        )
    )
    db.session.commit()

    options_json = webauthn_helpers.build_registration_options_json(
        user_id, challenge_bytes
    )

    return render_template(
        "setup.html",
        challenge_id=challenge_id,
        options_json=options_json,
        nonce=g.nonce,
    )


# ---------------------------------------------------------------------------
# POST /setup/complete  —  process WebAuthn registration response
# ---------------------------------------------------------------------------


@setup_bp.route("/setup/complete", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATE_LIMIT_SETUP_COMPLETE"])
def setup_complete():
    if not session.get("oidc_request") or not session.get("user_id"):
        return jsonify({"error": _("No active session.")}), HTTPStatus.UNAUTHORIZED

    data = request.get_json()
    if not data:
        return jsonify({"error": _("Missing JSON body.")}), HTTPStatus.BAD_REQUEST

    user_id = session["user_id"]
    challenge_id = data.get("challenge_id", "")

    # Consume the challenge (single-use, TTL check)
    ch = db.session.get(Challenge, challenge_id)
    if not ch or ch.user_id != user_id or ch.used:
        return jsonify({"error": _("Invalid challenge.")}), HTTPStatus.BAD_REQUEST

    exp = ch.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > exp:
        return jsonify({"error": _("Challenge expired.")}), HTTPStatus.BAD_REQUEST

    ch.used = True
    db.session.commit()
    challenge_bytes = bytes(ch.challenge)

    # Build the credential JSON structure expected by py_webauthn
    credential_json = json.dumps(
        {
            "id": data.get("id"),
            "rawId": data.get("rawId"),
            "type": data.get("type"),
            "transports": data.get("transports", []),
            "response": data.get("response", {}),
        }
    )

    try:
        reg = webauthn_helpers.verify_registration(challenge_bytes, credential_json)
    except ValueError as exc:
        audit_log(ACTION_SETUP, METHOD_WEBAUTHN_ROAMING, user_id)
        return jsonify({"error": str(exc)}), HTTPStatus.BAD_REQUEST

    auth_type = reg.get("authenticator_type", "roaming")
    method = (
        METHOD_WEBAUTHN_PLATFORM if auth_type == "platform" else METHOD_WEBAUTHN_ROAMING
    )

    db.session.add(
        Credential(
            credential_id=reg["credential_id"],
            user_id=user_id,
            public_key=reg["public_key"],
            sign_count=reg["sign_count"],
            authenticator_type=auth_type,
            device_type=reg.get("device_type", "single_device"),
            transport=reg.get("transport") or "",
            is_passkey=reg["is_passkey"],
        )
    )

    # Generate single-use backup codes and store their bcrypt hashes
    codes = CryptoService.generate_backup_codes(BACKUP_CODES_COUNT)
    for code_hash in [CryptoService.hash_backup_code(c) for c in codes]:
        db.session.add(BackupCode(code_hash=code_hash, user_id=user_id))

    db.session.commit()
    audit_log(ACTION_SETUP, method, user_id)

    # Store backup codes in session for one-time display, mark 2FA as verified
    session["backup_codes"] = codes
    session["2fa_verified"] = True

    return jsonify({"redirect_url": url_for("setup.setup_done")})


# ---------------------------------------------------------------------------
# GET /setup/done  —  one-time backup code display
# ---------------------------------------------------------------------------


@setup_bp.route("/setup/done")
def setup_done():
    backup_codes = session.pop("backup_codes", [])
    if not backup_codes and not session.get("2fa_verified"):
        abort(
            HTTPStatus.BAD_REQUEST,
            _("No active setup session. Please restart the login process."),
        )

    # Reconstruct the /authorize URL to continue the OIDC flow
    from app.src.x2fa.app.routes.auth import _authorize_continue_url

    continue_url = _authorize_continue_url()

    return render_template(
        "setup_done.html",
        backup_codes=backup_codes,
        continue_url=continue_url,
        nonce=g.nonce,
    )
