"""Integrationstests für FIDO2-Routen (/setup, /verify)."""

import json
from unittest.mock import patch


# ---------------------------------------------------------------------------
# GET /setup
# ---------------------------------------------------------------------------

def test_setup_get_no_token(client):
    status, _, _ = client.get("/setup")
    assert status.startswith("400")


def test_setup_get_invalid_token(client):
    status, _, _ = client.get("/setup", query="token=INVALID")
    assert status.startswith("400")


def test_setup_get_wrong_action(client):
    from crypto import create_jwt
    token = create_jwt({"sub": "u1", "action": "verify", "return_url": "https://app/cb"}, 5)
    status, _, _ = client.get("/setup", query=f"token={token}")
    assert status.startswith("400")


def test_setup_get_valid(client, setup_token):
    status, headers, body = client.get("/setup", query=f"token={setup_token}")
    assert status.startswith("200")
    assert "Content-Security-Policy" in headers
    assert b"nonce=" in body
    assert b"navigator.credentials.create" in body


def test_setup_get_creates_challenge(client, setup_token):
    from repositories import ChallengeRepo
    client.get("/setup", query=f"token={setup_token}")
    # Challenge wurde für den User angelegt
    from models import SessionLocal, Challenge
    with SessionLocal() as db:
        count = db.query(Challenge).filter_by(user_id="user_test").count()
    assert count == 1


# ---------------------------------------------------------------------------
# POST /setup/complete
# ---------------------------------------------------------------------------

def _fake_reg_result():
    return {
        "credential_id": b"fake_credential_id_12345",
        "public_key": b"fake_public_key_bytes",
        "sign_count": 0,
        "is_passkey": False,
    }


def test_setup_complete_missing_body(client):
    status, _, body = client.post_json("/setup/complete", {})
    assert status.startswith("400")


def test_setup_complete_invalid_token(client):
    status, _, _ = client.post_json("/setup/complete", {"token": "BAD"})
    assert status.startswith("401")


def test_setup_complete_invalid_challenge(client, setup_token):
    with patch("webauthn_helpers.verify_registration", return_value=_fake_reg_result()):
        status, _, body = client.post_json("/setup/complete", {
            "token": setup_token,
            "challenge_id": "nonexistent-id",
            "id": "abc", "rawId": "abc", "type": "public-key",
            "response": {"clientDataJSON": "x", "attestationObject": "y"},
        })
    assert status.startswith("400")


def test_setup_complete_success(client, setup_token):
    # Erst GET um Challenge zu erzeugen
    _, _, body = client.get("/setup", query=f"token={setup_token}")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_registration", return_value=_fake_reg_result()):
        status, _, resp_body = client.post_json("/setup/complete", {
            "token": setup_token,
            "challenge_id": challenge_id,
            "id": "ZmFrZQ", "rawId": "ZmFrZQ", "type": "public-key",
            "response": {"clientDataJSON": "x", "attestationObject": "y"},
        })

    assert status.startswith("200")
    data = json.loads(resp_body)
    assert "redirect_url" in data
    assert "backup_codes" in data
    assert len(data["backup_codes"]) == 10


def test_setup_complete_webauthn_failure(client, setup_token):
    _, _, body = client.get("/setup", query=f"token={setup_token}")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_registration", side_effect=ValueError("Attestation invalid")):
        status, _, resp_body = client.post_json("/setup/complete", {
            "token": setup_token,
            "challenge_id": challenge_id,
            "id": "x", "rawId": "x", "type": "public-key",
            "response": {},
        })

    assert status.startswith("400")
    assert b"Attestation invalid" in resp_body


def test_setup_complete_challenge_reuse(client, setup_token):
    """Challenge darf nur einmal verwendet werden."""
    _, _, body = client.get("/setup", query=f"token={setup_token}")
    challenge_id = _extract_challenge_id(body)

    payload = {
        "token": setup_token,
        "challenge_id": challenge_id,
        "id": "ZmFrZQ", "rawId": "ZmFrZQ", "type": "public-key",
        "response": {"clientDataJSON": "x", "attestationObject": "y"},
    }

    with patch("webauthn_helpers.verify_registration", return_value=_fake_reg_result()):
        client.post_json("/setup/complete", payload)
        status, _, _ = client.post_json("/setup/complete", payload)

    assert status.startswith("400")


# ---------------------------------------------------------------------------
# GET /verify
# ---------------------------------------------------------------------------

def test_verify_get_no_credentials_redirects_to_totp(client, verify_token):
    status, headers, _ = client.get("/verify", query=f"token={verify_token}")
    assert status.startswith("302")
    assert "/totp/verify" in headers.get("Location", "")


def test_verify_get_with_credentials(client, verify_token):
    from repositories import CredentialRepo
    CredentialRepo.save(
        credential_id=b"cred1234",
        user_id="user_test",
        public_key=b"pubkey",
        sign_count=0,
        authenticator_type="platform",
    )
    status, headers, body = client.get("/verify", query=f"token={verify_token}")
    assert status.startswith("200")
    assert b"navigator.credentials.get" in body
    assert "Content-Security-Policy" in headers


# ---------------------------------------------------------------------------
# POST /verify/complete
# ---------------------------------------------------------------------------

def test_verify_complete_success(client, verify_token):
    from repositories import CredentialRepo
    from webauthn import base64url_to_bytes
    import base64

    cred_id = b"cred_verify_test"
    cred_id_b64 = base64.urlsafe_b64encode(cred_id).rstrip(b"=").decode()

    CredentialRepo.save(
        credential_id=cred_id,
        user_id="user_test",
        public_key=b"pubkey",
        sign_count=5,
        authenticator_type="platform",
    )

    # Challenge erzeugen
    _, _, body = client.get("/verify", query=f"token={verify_token}")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_authentication", return_value=6):
        status, _, resp_body = client.post_json("/verify/complete", {
            "token": verify_token,
            "challenge_id": challenge_id,
            "id": cred_id_b64,
            "rawId": cred_id_b64,
            "type": "public-key",
            "response": {
                "clientDataJSON": "x",
                "authenticatorData": "y",
                "signature": "z",
                "userHandle": None,
            },
        })

    assert status.startswith("200")
    data = json.loads(resp_body)
    assert "redirect_url" in data
    assert "token=" in data["redirect_url"]


def test_verify_complete_webauthn_failure(client, verify_token):
    from repositories import CredentialRepo
    import base64

    cred_id = b"cred_fail_test"
    cred_id_b64 = base64.urlsafe_b64encode(cred_id).rstrip(b"=").decode()

    CredentialRepo.save(
        credential_id=cred_id,
        user_id="user_test",
        public_key=b"pubkey",
        sign_count=5,
        authenticator_type="platform",
    )

    _, _, body = client.get("/verify", query=f"token={verify_token}")
    challenge_id = _extract_challenge_id(body)

    with patch("webauthn_helpers.verify_authentication", side_effect=ValueError("bad signature")):
        status, _, resp_body = client.post_json("/verify/complete", {
            "token": verify_token,
            "challenge_id": challenge_id,
            "id": cred_id_b64,
            "rawId": cred_id_b64,
            "type": "public-key",
            "response": {"clientDataJSON": "x", "authenticatorData": "y", "signature": "z"},
        })

    assert status.startswith("400")


# ---------------------------------------------------------------------------
# Hilfsfunktion
# ---------------------------------------------------------------------------

def _extract_challenge_id(html: bytes) -> str:
    """Extrahiert CHALLENGE_ID aus dem HTML des Templates."""
    for line in html.decode().splitlines():
        if "CHALLENGE_ID" in line:
            # const CHALLENGE_ID = "uuid-here";
            start = line.index('"') + 1
            end = line.rindex('"')
            return line[start:end]
    raise ValueError("CHALLENGE_ID nicht in HTML gefunden")
