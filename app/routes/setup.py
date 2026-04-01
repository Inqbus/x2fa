"""2FA-Setup-Routes: Methodenauswahl, WebAuthn-Registrierung, Backup-Codes."""

import json
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from flask import (
    Blueprint, abort, current_app, g, jsonify, redirect,
    render_template, request, session, url_for,
)

from app.extensions import db, limiter
from app.models import BackupCode, Challenge, Credential
from app.routes import (
    ACTION_SETUP, METHOD_WEBAUTHN_PLATFORM, METHOD_WEBAUTHN_ROAMING, audit_log,
)

setup_bp = Blueprint("setup", __name__)


def _require_session():
    """Prüft ob eine aktive OIDC-Session vorhanden ist."""
    if not session.get("oidc_request") or not session.get("user_id"):
        abort(400, "Keine aktive Sitzung. Bitte starte den Login-Prozess neu.")


# ---------------------------------------------------------------------------
# GET /setup  →  Methodenauswahl
# ---------------------------------------------------------------------------

@setup_bp.route("/setup")
def setup_choose():
    _require_session()
    return render_template("setup_choose.html", nonce=g.nonce)


# ---------------------------------------------------------------------------
# GET /setup/webauthn
# ---------------------------------------------------------------------------

@setup_bp.route("/setup/webauthn")
def setup_webauthn_get():
    _require_session()
    user_id = session["user_id"]

    challenge_bytes = secrets.token_bytes(32)
    challenge_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)

    db.session.add(Challenge(
        challenge_id=challenge_id,
        user_id=user_id,
        challenge=challenge_bytes,
        expires_at=expires_at,
    ))
    db.session.commit()

    import webauthn_helpers
    options_json = webauthn_helpers.build_registration_options_json(user_id, challenge_bytes)

    return render_template(
        "setup.html",
        challenge_id=challenge_id,
        options_json=options_json,
        nonce=g.nonce,
    )


# ---------------------------------------------------------------------------
# POST /setup/complete  →  WebAuthn-Registrierung abschließen
# ---------------------------------------------------------------------------

@setup_bp.route("/setup/complete", methods=["POST"])
@limiter.limit("5 per minute")
def setup_complete():
    if not session.get("oidc_request") or not session.get("user_id"):
        return jsonify({"error": "Keine aktive Sitzung."}), 401

    data = request.get_json()
    if not data:
        return jsonify({"error": "Kein JSON-Body."}), 400

    user_id      = session["user_id"]
    challenge_id = data.get("challenge_id", "")

    # Challenge laden und konsumieren
    ch = Challenge.query.get(challenge_id)
    if not ch or ch.user_id != user_id or ch.used:
        return jsonify({"error": "Challenge ungültig."}), 400

    exp = ch.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > exp:
        return jsonify({"error": "Challenge abgelaufen."}), 400

    ch.used = True
    db.session.commit()
    challenge_bytes = bytes(ch.challenge)

    # Credential-JSON zusammensetzen
    credential_json = json.dumps({
        "id":         data.get("id"),
        "rawId":      data.get("rawId"),
        "type":       data.get("type"),
        "transports": data.get("transports", []),
        "response":   data.get("response", {}),
    })

    import webauthn_helpers
    try:
        reg = webauthn_helpers.verify_registration(challenge_bytes, credential_json)
    except ValueError as exc:
        audit_log(ACTION_SETUP, METHOD_WEBAUTHN_ROAMING, user_id)
        return jsonify({"error": str(exc)}), 400

    auth_type = reg.get("authenticator_type", "roaming")
    method = (
        METHOD_WEBAUTHN_PLATFORM if auth_type == "platform"
        else METHOD_WEBAUTHN_ROAMING
    )

    # Credential speichern
    db.session.add(Credential(
        credential_id=reg["credential_id"],
        user_id=user_id,
        public_key=reg["public_key"],
        sign_count=reg["sign_count"],
        authenticator_type=auth_type,
        device_type=reg.get("device_type", "single_device"),
        transport=reg.get("transport"),
        is_passkey=reg["is_passkey"],
    ))

    # Backup-Codes generieren (einmalig)
    from app.services.crypto import CryptoService
    codes = CryptoService.generate_backup_codes(10)
    for code_hash in [CryptoService.hash_backup_code(c) for c in codes]:
        db.session.add(BackupCode(code_hash=code_hash, user_id=user_id))

    db.session.commit()
    audit_log(ACTION_SETUP, method, user_id)

    # Backup-Codes temporär in Session, 2FA als verifiziert markieren
    session["backup_codes"] = codes
    session["2fa_verified"] = True

    return jsonify({"redirect_url": url_for("setup.setup_done")})


# ---------------------------------------------------------------------------
# GET /setup/done  →  Backup-Codes anzeigen (einmalig)
# ---------------------------------------------------------------------------

@setup_bp.route("/setup/done")
def setup_done():
    backup_codes = session.pop("backup_codes", [])
    if not backup_codes and not session.get("2fa_verified"):
        return redirect(url_for("auth.authorize"))

    # Continue-URL mit OIDC-Params rekonstruieren
    from app.routes.auth import _authorize_continue_url
    continue_url = _authorize_continue_url()

    return render_template(
        "setup_done.html",
        backup_codes=backup_codes,
        continue_url=continue_url,
        nonce=g.nonce,
    )
