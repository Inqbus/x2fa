"""WebAuthn assertion (verification) routes."""

import json
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, abort, g, jsonify, redirect,
    render_template, request, session, url_for,
)

from app.extensions import db, limiter
from app.models import Challenge, Credential
from app.routes import (
    ACTION_FAIL, ACTION_VERIFY,
    METHOD_WEBAUTHN_PLATFORM, METHOD_WEBAUTHN_ROAMING,
    audit_log,
)

verify_bp = Blueprint("verify", __name__)


def _require_session():
    """Aborts with 400 if no active OIDC session is present."""
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(400, "No active session. Please restart the login process.")


# ---------------------------------------------------------------------------
# GET /verify
# ---------------------------------------------------------------------------

@verify_bp.route("/verify")
def verify_get():
    _require_session()
    user_id = session["user_id"]

    credentials = Credential.query.filter_by(user_id=user_id).all()
    if not credentials:
        # No WebAuthn credential registered — fall back to TOTP
        return redirect(url_for("totp.totp_verify_get"))

    challenge_bytes = secrets.token_bytes(32)
    challenge_id    = str(uuid.uuid4())
    expires_at      = datetime.now(timezone.utc) + timedelta(minutes=5)

    db.session.add(Challenge(
        challenge_id=challenge_id,
        user_id=user_id,
        challenge=challenge_bytes,
        expires_at=expires_at,
    ))
    db.session.commit()

    credential_ids   = [bytes(c.credential_id) for c in credentials]
    transports_list  = [
        c.transport.split(",") if c.transport else []
        for c in credentials
    ]

    import webauthn_helpers
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
@limiter.limit("10 per minute; 30 per hour")
def verify_complete():
    if not session.get("oidc_request") or not session.get("user_id"):
        return jsonify({"error": "No active session."}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON body."}), 400

    user_id      = session["user_id"]
    challenge_id = data.get("challenge_id", "")

    # Consume the challenge (single-use, TTL check)
    ch = Challenge.query.get(challenge_id)
    if not ch or ch.user_id != user_id or ch.used:
        return jsonify({"error": "Invalid challenge."}), 400

    exp = ch.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > exp:
        return jsonify({"error": "Challenge expired."}), 400

    ch.used = True
    db.session.commit()
    challenge_bytes = bytes(ch.challenge)

    # Decode rawId to look up the stored credential
    from webauthn import base64url_to_bytes
    try:
        raw_id = base64url_to_bytes(data.get("rawId", ""))
    except Exception:
        return jsonify({"error": "Invalid credential ID."}), 400

    cred = Credential.query.get(raw_id)
    if cred is None or cred.user_id != user_id:
        return jsonify({"error": "Credential not found."}), 404

    credential_json = json.dumps({
        "id":       data.get("id"),
        "rawId":    data.get("rawId"),
        "type":     data.get("type"),
        "response": data.get("response", {}),
    })

    import webauthn_helpers
    try:
        new_sign_count = webauthn_helpers.verify_authentication(
            challenge=challenge_bytes,
            credential_json=credential_json,
            stored_public_key=bytes(cred.public_key),
            stored_sign_count=cred.sign_count,
        )
    except ValueError as exc:
        audit_log(ACTION_FAIL, METHOD_WEBAUTHN_ROAMING, user_id)
        return jsonify({"error": str(exc)}), 400

    # Update sign count — regression would indicate a cloned authenticator
    cred.sign_count = new_sign_count
    cred.last_used_at = datetime.now(timezone.utc)
    db.session.commit()

    method = (
        METHOD_WEBAUTHN_PLATFORM if cred.authenticator_type == "platform"
        else METHOD_WEBAUTHN_ROAMING
    )
    audit_log(ACTION_VERIFY, method, user_id)

    # Mark 2FA as complete and redirect back to the authorization endpoint
    session["2fa_verified"] = True
    from app.routes.auth import _authorize_continue_url
    return jsonify({"redirect_url": _authorize_continue_url()})
