"""X2FA – Bottle-Routen für FIDO2 Setup/Verify, TOTP-Fallback und Backup-Codes."""

import json
import os
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

from bottle import Bottle, abort, request, response, static_file

import audit
import crypto
import totp_helpers
import webauthn_helpers
from repositories import BackupRepo, ChallengeRepo, CredentialRepo, TOTPRepo

app = Bottle()

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
DOMAIN = os.environ.get("X2FA_DOMAIN", "localhost")

_ERROR_TITLES = {
    400: "Ungültige Anfrage",
    401: "Nicht autorisiert",
    403: "Zugriff verweigert",
    404: "Nicht gefunden",
    500: "Interner Fehler",
}

_ERROR_MESSAGES = {
    400: "Die Anfrage konnte nicht verarbeitet werden.",
    401: "Bitte melde dich erneut an.",
    403: "Du hast keine Berechtigung für diese Seite.",
    404: "Die aufgerufene Seite existiert nicht.",
    500: "Ein unerwarteter Fehler ist aufgetreten. Bitte versuche es später erneut.",
}


def _error_page(code: int, message: str | None = None) -> str:
    response.content_type = "text/html; charset=utf-8"
    return _render(
        "error.html",
        status_code=str(code),
        title=_ERROR_TITLES.get(code, "Fehler"),
        message=message or _ERROR_MESSAGES.get(code, ""),
    )


@app.error(400)
def error_400(err):
    return _error_page(400, err.body)

@app.error(401)
def error_401(err):
    return _error_page(401, err.body)

@app.error(403)
def error_403(err):
    return _error_page(403, err.body)

@app.error(404)
def error_404(err):
    return _error_page(404, err.body)

@app.error(500)
def error_500(err):
    return _error_page(500)


# ---------------------------------------------------------------------------
# Demo-Callback (nur für lokale Tests — nicht in Produktion verwenden)
# ---------------------------------------------------------------------------

@app.route("/done")
def demo_callback():
    token = request.query.get("token", "")
    if not token:
        return "<h2>Kein Token empfangen.</h2>"
    try:
        payload = crypto.verify_jwt(token)
    except Exception as e:
        return f"<h2>Token ungültig:</h2><pre>{e}</pre>"

    rows = "".join(f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in payload.items())
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="UTF-8">
<title>Demo-Callback</title>
<style>body{{font-family:system-ui;max-width:500px;margin:60px auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td{{padding:.5rem;border-bottom:1px solid #eee}}
.ok{{color:#16a34a;font-size:1.3rem;font-weight:bold}}</style></head>
<body>
<p class="ok">&#10003; 2FA erfolgreich</p>
<table>{rows}</table>
<p style="color:#888;font-size:.85rem;margin-top:2rem">
  Dies ist ein Test-Endpunkt. In der echten Anwendung verarbeitet dein Server diesen JWT.
</p>
</body></html>"""


# In-Memory Rate-Limiter: user_id → [timestamp, ...]
_backup_attempts: dict[str, list[float]] = {}


def _backup_rate_limit_ok(user_id: str, max_attempts: int = 5, window: int = 60) -> bool:
    now = time.monotonic()
    attempts = [t for t in _backup_attempts.get(user_id, []) if now - t < window]
    if len(attempts) >= max_attempts:
        _backup_attempts[user_id] = attempts
        return False
    attempts.append(now)
    _backup_attempts[user_id] = attempts
    return True

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _render(template_name: str, **kwargs) -> str:
    """Liest Template-Datei und ersetzt {{key}} / {{!key}} Platzhalter."""
    path = os.path.join(TEMPLATE_DIR, template_name)
    with open(path, encoding="utf-8") as f:
        html = f.read()
    for key, value in kwargs.items():
        html = html.replace("{{!" + key + "}}", str(value))   # unescaped (JSON)
        html = html.replace("{{" + key + "}}", _escape(str(value)))
    return html


def _escape(s: str) -> str:
    """Minimales HTML-Escaping für Template-Werte."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#x27;")
    )


def _csp_nonce() -> str:
    return secrets.token_urlsafe(16)


def _set_csp(nonce: str, allow_data_images: bool = False) -> None:
    img_src = "img-src data:; " if allow_data_images else ""
    response.set_header(
        "Content-Security-Policy",
        f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
        f"{img_src}form-action https: http:; base-uri 'none'; frame-ancestors 'none';",
    )
    response.set_header("X-Frame-Options", "DENY")
    response.set_header("X-Content-Type-Options", "nosniff")


def _validate_request_jwt(required_action: str) -> dict:
    """Liest und validiert den JWT aus dem Query-String."""
    token = request.query.get("token", "")
    if not token:
        abort(400, "Fehlender token-Parameter.")
    try:
        payload = crypto.verify_jwt(token)
    except Exception:
        abort(400, "Ungültiger oder abgelaufener Token.")
    if payload.get("action") != required_action:
        abort(400, f"Falscher Token-Typ (erwartet: {required_action}).")
    return payload


def _json_response(data: dict, status: int = 200) -> str:
    response.content_type = "application/json"
    response.status = status
    return json.dumps(data)


def _error_json(message: str, status: int = 400) -> str:
    return _json_response({"error": message}, status)


def _client_ip() -> str:
    """Gibt die Client-IP zurück (X-Forwarded-For hat Vorrang hinter Reverse-Proxy)."""
    return (
        request.environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.environ.get("REMOTE_ADDR", "unknown")
    )


# ---------------------------------------------------------------------------
# GET /setup
# ---------------------------------------------------------------------------

@app.route("/setup")
def setup_get():
    payload = _validate_request_jwt("setup")
    user_id = payload["sub"]

    challenge = secrets.token_bytes(32)
    challenge_id = ChallengeRepo.create(user_id, challenge)

    options_json = webauthn_helpers.build_registration_options_json(user_id, challenge)
    nonce = _csp_nonce()
    _set_csp(nonce)
    response.content_type = "text/html; charset=utf-8"

    return _render(
        "setup.html",
        token=request.query.get("token"),
        challenge_id=challenge_id,
        options_json=options_json,
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# POST /setup/complete
# ---------------------------------------------------------------------------

@app.route("/setup/complete", method="POST")
def setup_complete():
    data = request.json
    if not data:
        return _error_json("Kein JSON-Body.")

    token = data.get("token", "")
    challenge_id = data.get("challenge_id", "")

    try:
        payload = crypto.verify_jwt(token)
    except Exception:
        return _error_json("Ungültiger oder abgelaufener Token.", 401)

    if payload.get("action") != "setup":
        return _error_json("Falscher Token-Typ.", 400)

    user_id = payload["sub"]

    # Challenge konsumieren (einmalig, TTL-geprüft)
    challenge = ChallengeRepo.consume(challenge_id, user_id)
    if challenge is None:
        return _error_json("Challenge ungültig oder abgelaufen.", 400)

    # Credential-JSON aus den Browser-Feldern zusammensetzen
    credential_json = json.dumps({
        "id": data.get("id"),
        "rawId": data.get("rawId"),
        "type": data.get("type"),
        "response": data.get("response", {}),
    })

    try:
        reg = webauthn_helpers.verify_registration(challenge, credential_json)
    except ValueError as exc:
        audit.log(audit.FIDO2_SETUP_FAIL, user_id, _client_ip(), False, str(exc))
        return _error_json(str(exc), 400)

    CredentialRepo.save(
        credential_id=reg["credential_id"],
        user_id=user_id,
        public_key=reg["public_key"],
        sign_count=reg["sign_count"],
        authenticator_type=reg.get("authenticator_type", "roaming"),
        is_passkey=reg["is_passkey"],
    )

    # 10 Backup-Codes generieren
    codes = crypto.generate_backup_codes(10)
    code_hashes = [crypto.hash_backup_code(c) for c in codes]
    BackupRepo.save_many(user_id, code_hashes)

    audit.log(audit.FIDO2_SETUP_OK, user_id, _client_ip(), True)

    # Return-JWT für die Hauptanwendung (1 Minute gültig)
    return_token = crypto.create_jwt(
        {"sub": user_id, "result": "success", "amr": ["fido2"]},
        expiry_minutes=1,
    )
    return_url = payload.get("return_url", "/")
    redirect_url = f"{return_url}?token={return_token}"

    # Backup-Codes werden einmalig im Response zurückgegeben
    return _json_response({
        "redirect_url": redirect_url,
        "backup_codes": codes,  # Einmalig – danach nie wieder abrufbar
    })


# ---------------------------------------------------------------------------
# GET /verify
# ---------------------------------------------------------------------------

@app.route("/verify")
def verify_get():
    payload = _validate_request_jwt("verify")
    user_id = payload["sub"]

    credentials = CredentialRepo.list_by_user(user_id)
    if not credentials:
        # Kein Schlüssel registriert → TOTP-Fallback
        token = request.query.get("token")
        response.status = 302
        response.set_header("Location", f"/totp/verify?token={token}")
        return ""

    credential_ids = [bytes(cred.credential_id) for cred in credentials]
    challenge = secrets.token_bytes(32)
    challenge_id = ChallengeRepo.create(user_id, challenge)

    options_json = webauthn_helpers.build_authentication_options_json(challenge, credential_ids)
    nonce = _csp_nonce()
    _set_csp(nonce)
    response.content_type = "text/html; charset=utf-8"

    return _render(
        "verify.html",
        token=request.query.get("token"),
        challenge_id=challenge_id,
        options_json=options_json,
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# POST /verify/complete
# ---------------------------------------------------------------------------

@app.route("/verify/complete", method="POST")
def verify_complete():
    data = request.json
    if not data:
        return _error_json("Kein JSON-Body.")

    token = data.get("token", "")
    challenge_id = data.get("challenge_id", "")

    try:
        payload = crypto.verify_jwt(token)
    except Exception:
        return _error_json("Ungültiger oder abgelaufener Token.", 401)

    if payload.get("action") != "verify":
        return _error_json("Falscher Token-Typ.", 400)

    user_id = payload["sub"]

    challenge = ChallengeRepo.consume(challenge_id, user_id)
    if challenge is None:
        return _error_json("Challenge ungültig oder abgelaufen.", 400)

    # Credential aus DB laden
    from webauthn import base64url_to_bytes
    try:
        raw_id = base64url_to_bytes(data.get("rawId", ""))
    except Exception:
        return _error_json("Ungültige Credential-ID.", 400)

    cred = CredentialRepo.get_by_id(raw_id)
    if cred is None or cred.user_id != user_id:
        return _error_json("Credential nicht gefunden.", 404)

    credential_json = json.dumps({
        "id": data.get("id"),
        "rawId": data.get("rawId"),
        "type": data.get("type"),
        "response": data.get("response", {}),
    })

    try:
        new_sign_count = webauthn_helpers.verify_authentication(
            challenge=challenge,
            credential_json=credential_json,
            stored_public_key=bytes(cred.public_key),
            stored_sign_count=cred.sign_count,
        )
    except ValueError as exc:
        audit.log(audit.FIDO2_VERIFY_FAIL, user_id, _client_ip(), False, str(exc))
        return _error_json(str(exc), 400)

    CredentialRepo.update_sign_count(raw_id, new_sign_count)
    audit.log(audit.FIDO2_VERIFY_OK, user_id, _client_ip(), True)

    return_token = crypto.create_jwt(
        {"sub": user_id, "result": "verified", "amr": ["fido2"]},
        expiry_minutes=1,
    )
    return_url = payload.get("return_url", "/")
    redirect_url = f"{return_url}?token={return_token}"

    return _json_response({"redirect_url": redirect_url})


# ---------------------------------------------------------------------------
# GET /totp/setup
# ---------------------------------------------------------------------------

@app.route("/totp/setup")
def totp_setup_get():
    payload = _validate_request_jwt("setup")
    user_id = payload["sub"]

    secret = totp_helpers.generate_secret()
    secret_encrypted = crypto.encrypt_totp_secret(secret)
    TOTPRepo.save(user_id, secret_encrypted)

    provisioning_uri = totp_helpers.build_provisioning_uri(secret, user_id, issuer=DOMAIN)
    qr_data_uri = totp_helpers.generate_qr_data_uri(provisioning_uri)

    nonce = _csp_nonce()
    _set_csp(nonce, allow_data_images=True)
    response.content_type = "text/html; charset=utf-8"

    return _render(
        "totp_setup.html",
        token=request.query.get("token"),
        secret=secret,
        qr_data_uri=qr_data_uri,
        error=request.query.get("error", ""),
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# POST /totp/setup/verify
# ---------------------------------------------------------------------------

@app.route("/totp/setup/verify", method="POST")
def totp_setup_verify():
    token = request.forms.get("token", "")
    code = request.forms.get("code", "").strip()

    try:
        payload = crypto.verify_jwt(token)
    except Exception:
        abort(400, "Ungültiger oder abgelaufener Token.")

    if payload.get("action") != "setup":
        abort(400, "Falscher Token-Typ.")

    user_id = payload["sub"]

    totp_record = TOTPRepo.get(user_id)
    if totp_record is None:
        abort(400, "Kein TOTP-Secret gefunden. Bitte Setup erneut starten.")

    secret = crypto.decrypt_totp_secret(bytes(totp_record.secret_encrypted))

    if not totp_helpers.verify_code(secret, code):
        audit.log(audit.TOTP_VERIFY_FAIL, user_id, _client_ip(), False, "setup_verify")
        response.status = 302
        response.set_header("Location", f"/totp/setup?token={token}&error=Falscher+Code.+Bitte+erneut+versuchen.")
        return ""

    TOTPRepo.set_verified(user_id)
    audit.log(audit.TOTP_SETUP_OK, user_id, _client_ip(), True)

    return_token = crypto.create_jwt(
        {"sub": user_id, "result": "success", "amr": ["totp"]},
        expiry_minutes=1,
    )
    return_url = payload.get("return_url", "/")
    response.status = 302
    response.set_header("Location", f"{return_url}?token={return_token}")
    return ""


# ---------------------------------------------------------------------------
# GET /totp/verify
# ---------------------------------------------------------------------------

@app.route("/totp/verify")
def totp_verify_get():
    payload = _validate_request_jwt("verify")
    user_id = payload["sub"]

    totp_record = TOTPRepo.get(user_id)
    if totp_record is None or not totp_record.verified:
        abort(400, "Kein verifiziertes TOTP-Secret vorhanden.")

    nonce = _csp_nonce()
    _set_csp(nonce)
    response.content_type = "text/html; charset=utf-8"

    return _render(
        "totp_verify.html",
        token=request.query.get("token"),
        error=request.query.get("error", ""),
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# POST /totp/verify
# ---------------------------------------------------------------------------

@app.route("/totp/verify", method="POST")
def totp_verify_post():
    token = request.forms.get("token", "")
    code = request.forms.get("code", "").strip()

    try:
        payload = crypto.verify_jwt(token)
    except Exception:
        abort(400, "Ungültiger oder abgelaufener Token.")

    if payload.get("action") != "verify":
        abort(400, "Falscher Token-Typ.")

    user_id = payload["sub"]

    totp_record = TOTPRepo.get(user_id)
    if totp_record is None or not totp_record.verified:
        abort(400, "Kein verifiziertes TOTP-Secret vorhanden.")

    secret = crypto.decrypt_totp_secret(bytes(totp_record.secret_encrypted))
    last_used = totp_record.last_used_at

    if not totp_helpers.verify_code(secret, code, last_used_at=last_used):
        audit.log(audit.TOTP_VERIFY_FAIL, user_id, _client_ip(), False)
        response.status = 302
        response.set_header("Location", f"/totp/verify?token={token}&error=Falscher+oder+bereits+verwendeter+Code.")
        return ""

    TOTPRepo.update_last_used(user_id)
    audit.log(audit.TOTP_VERIFY_OK, user_id, _client_ip(), True)

    return_token = crypto.create_jwt(
        {"sub": user_id, "result": "verified", "amr": ["totp"]},
        expiry_minutes=1,
    )
    return_url = payload.get("return_url", "/")
    response.status = 302
    response.set_header("Location", f"{return_url}?token={return_token}")
    return ""


# ---------------------------------------------------------------------------
# GET /backup/verify
# ---------------------------------------------------------------------------

@app.route("/backup/verify")
def backup_verify_get():
    _validate_request_jwt("verify")

    nonce = _csp_nonce()
    _set_csp(nonce)
    response.content_type = "text/html; charset=utf-8"

    return _render(
        "backup_verify.html",
        token=request.query.get("token"),
        error=request.query.get("error", ""),
        nonce=nonce,
    )


# ---------------------------------------------------------------------------
# POST /backup/verify
# ---------------------------------------------------------------------------

@app.route("/backup/verify", method="POST")
def backup_verify_post():
    token = request.forms.get("token", "")
    code = request.forms.get("code", "").strip().upper()

    try:
        payload = crypto.verify_jwt(token)
    except Exception:
        abort(400, "Ungültiger oder abgelaufener Token.")

    if payload.get("action") != "verify":
        abort(400, "Falscher Token-Typ.")

    user_id = payload["sub"]

    # Rate-Limit: max 5 Versuche pro Minute
    if not _backup_rate_limit_ok(user_id):
        audit.log(audit.BACKUP_RATE_LIMITED, user_id, _client_ip(), False)
        response.status = 302
        response.set_header("Location", f"/backup/verify?token={token}&error=Zu+viele+Versuche.+Bitte+1+Minute+warten.")
        return ""

    # Alle gültigen Codes des Users laden und gegen Code prüfen
    valid_codes = BackupRepo.find_valid(user_id)
    matched_hash = None
    for record in valid_codes:
        if crypto.verify_backup_code(code, record.code_hash):
            matched_hash = record.code_hash
            break

    if matched_hash is None:
        audit.log(audit.BACKUP_VERIFY_FAIL, user_id, _client_ip(), False)
        response.status = 302
        response.set_header("Location", f"/backup/verify?token={token}&error=Ungültiger+Backup-Code.")
        return ""

    BackupRepo.consume(matched_hash, user_id)
    remaining = BackupRepo.count_valid(user_id)
    audit.log(audit.BACKUP_VERIFY_OK, user_id, _client_ip(), True, f"remaining={remaining}")

    return_token = crypto.create_jwt(
        {"sub": user_id, "result": "verified", "amr": ["backup"], "remaining_codes": remaining},
        expiry_minutes=1,
    )
    return_url = payload.get("return_url", "/")
    response.status = 302
    response.set_header("Location", f"{return_url}?token={return_token}")
    return ""
