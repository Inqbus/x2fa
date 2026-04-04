"""Integration tests for WebAuthn routes (/setup/*, /verify, /verify/complete)."""

import json
from unittest.mock import patch


def _fake_reg_result():
    return {
        "credential_id":     b"fake_credential_id_12345",
        "public_key":        b"fake_public_key_bytes",
        "sign_count":        0,
        "is_passkey":        False,
        "authenticator_type": "roaming",
        "device_type":       "single_device",
        "transport":         None,
    }


def _create_credential(client, cred_id: bytes = b"cred1234", user_id: str = "user_test"):
    """Creates a WebAuthn credential directly in the DB."""
    from app.models import Credential, db
    with client.app_context():
        db.session.add(Credential(
            credential_id=cred_id,
            user_id=user_id,
            public_key=b"pubkey",
            sign_count=0,
            authenticator_type="platform",
            device_type="single_device",
        ))
        db.session.commit()


def _extract_challenge_id(html: bytes) -> str:
    """Extracts CHALLENGE_ID from the rendered template."""
    for line in html.decode().splitlines():
        if "CHALLENGE_ID" in line:
            start = line.index('"') + 1
            end   = line.rindex('"')
            return line[start:end]
    raise ValueError("CHALLENGE_ID not found in HTML")


# ---------------------------------------------------------------------------
# GET /setup  (Methoden-Auswahl)
# ---------------------------------------------------------------------------

def test_setup_choose_no_session(client):
    status, _, _ = client.get("/setup")
    assert status.startswith("400")


def test_setup_choose_valid(client):
    client.set_session(setup_mode=True)
    status, headers, body = client.get("/setup")
    assert status.startswith("200")
    assert "Content-Security-Policy" in headers
    assert b"/setup/webauthn" in body
    assert b"/totp/setup" in body


# ---------------------------------------------------------------------------
# GET /setup/webauthn
# ---------------------------------------------------------------------------

def test_setup_webauthn_get_no_session(client):
    status, _, _ = client.get("/setup/webauthn")
    assert status.startswith("400")


def test_setup_webauthn_get_valid(client):
    client.set_session(setup_mode=True)
    status, headers, body = client.get("/setup/webauthn")
    assert status.startswith("200")
    assert "Content-Security-Policy" in headers
    assert b"navigator.credentials.create" in body


def test_setup_webauthn_creates_challenge(client):
    from app.models import Challenge
    client.set_session(setup_mode=True)
    client.get("/setup/webauthn")
    with client.app_context():
        count = Challenge.query.filter_by(user_id="user_test").count()
    assert count == 1


# ---------------------------------------------------------------------------
# POST /setup/complete
# ---------------------------------------------------------------------------

def test_setup_complete_no_session(client):
    status, _, _ = client.post_json("/setup/complete", {"challenge_id": "x"})
    assert status.startswith("401")


def test_setup_complete_invalid_challenge(client):
    client.set_session(setup_mode=True)
    status, _, _ = client.post_json("/setup/complete", {
        "challenge_id": "nonexistent-id",
        "id": "abc", "rawId": "abc", "type": "public-key",
        "response": {"clientDataJSON": "x", "attestationObject": "y"},
    })
    assert status.startswith("400")


def test_setup_complete_success(client):
    client.set_session(setup_mode=True)
    _, _, body = client.get("/setup/webauthn")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_registration", return_value=_fake_reg_result()):
        status, _, resp_body = client.post_json("/setup/complete", {
            "challenge_id": challenge_id,
            "id": "ZmFrZQ", "rawId": "ZmFrZQ", "type": "public-key",
            "transports": [],
            "response": {"clientDataJSON": "x", "attestationObject": "y"},
        })

    assert status.startswith("200")
    data = json.loads(resp_body)
    assert "redirect_url" in data
    assert "/setup/done" in data["redirect_url"]


def test_setup_complete_webauthn_failure(client):
    client.set_session(setup_mode=True)
    _, _, body = client.get("/setup/webauthn")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_registration", side_effect=ValueError("Attestation invalid")):
        status, _, resp_body = client.post_json("/setup/complete", {
            "challenge_id": challenge_id,
            "id": "x", "rawId": "x", "type": "public-key",
            "response": {},
        })

    assert status.startswith("400")
    assert b"Attestation invalid" in resp_body


def test_setup_complete_challenge_reuse(client):
    """A challenge may only be redeemed once."""
    client.set_session(setup_mode=True)
    _, _, body = client.get("/setup/webauthn")
    challenge_id = _extract_challenge_id(body)

    payload = {
        "challenge_id": challenge_id,
        "id": "ZmFrZQ", "rawId": "ZmFrZQ", "type": "public-key",
        "transports": [],
        "response": {"clientDataJSON": "x", "attestationObject": "y"},
    }

    with patch("webauthn_helpers.verify_registration", return_value=_fake_reg_result()):
        client.post_json("/setup/complete", payload)
        status, _, _ = client.post_json("/setup/complete", payload)

    assert status.startswith("400")


# ---------------------------------------------------------------------------
# GET /verify
# ---------------------------------------------------------------------------

def test_verify_get_no_session(client):
    status, _, _ = client.get("/verify")
    assert status.startswith("400")


def test_verify_get_no_credentials_no_totp_redirects_to_rp(client):
    """No WebAuthn and no TOTP → RP receives access_denied (no state leak)."""
    client.set_session()
    status, headers, _ = client.get("/verify")
    assert status.startswith("302")
    assert "error=access_denied" in headers.get("Location", "")


def test_verify_get_with_credentials(client):
    _create_credential(client)
    client.set_session()
    status, headers, body = client.get("/verify")
    assert status.startswith("200")
    assert b"navigator.credentials.get" in body
    assert "Content-Security-Policy" in headers


# ---------------------------------------------------------------------------
# POST /verify/complete
# ---------------------------------------------------------------------------

def test_verify_complete_no_session(client):
    status, _, _ = client.post_json("/verify/complete", {"challenge_id": "x"})
    assert status.startswith("401")


def test_verify_complete_success(client):
    import base64
    cred_id     = b"cred_verify_test"
    cred_id_b64 = base64.urlsafe_b64encode(cred_id).rstrip(b"=").decode()

    _create_credential(client, cred_id=cred_id)
    client.set_session()
    _, _, body = client.get("/verify")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_authentication", return_value=1):
        status, _, resp_body = client.post_json("/verify/complete", {
            "challenge_id": challenge_id,
            "id":     cred_id_b64,
            "rawId":  cred_id_b64,
            "type":   "public-key",
            "response": {
                "clientDataJSON":    "x",
                "authenticatorData": "y",
                "signature":         "z",
                "userHandle":        None,
            },
        })

    assert status.startswith("200")
    data = json.loads(resp_body)
    assert "redirect_url" in data
    assert "/authorize" in data["redirect_url"]


def test_verify_complete_webauthn_failure(client):
    import base64
    cred_id     = b"cred_fail_test"
    cred_id_b64 = base64.urlsafe_b64encode(cred_id).rstrip(b"=").decode()

    _create_credential(client, cred_id=cred_id)
    client.set_session()
    _, _, body = client.get("/verify")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_authentication", side_effect=ValueError("bad signature")):
        status, _, _ = client.post_json("/verify/complete", {
            "challenge_id": challenge_id,
            "id":     cred_id_b64,
            "rawId":  cred_id_b64,
            "type":   "public-key",
            "response": {"clientDataJSON": "x", "authenticatorData": "y", "signature": "z"},
        })

    assert status.startswith("400")
