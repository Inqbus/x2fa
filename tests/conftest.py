"""Gemeinsame Fixtures für alle X2FA-Tests."""

import os
import sys

import pytest

# Projektverzeichnis in sys.path damit alle Module gefunden werden
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vendor"))

TEST_SECRET = "a" * 32
TEST_DOMAIN = "test.example.com"

# Standard-OIDC-Session für Tests (Verifikations-Flow)
_OIDC_REQUEST_VERIFY = {
    "client_id":             "test_client",
    "redirect_uri":          "https://app/cb",
    "scope":                 "openid",
    "state":                 "teststate",
    "nonce":                 "testnonce",
    "code_challenge":        "e3b0c44298fc1c149afbf4c8996fb924",
    "code_challenge_method": "S256",
    "response_type":         "code",
    "login_hint":            "user_test",
}


@pytest.fixture(scope="session", autouse=True)
def init_services():
    """Initialisiert Crypto und WebAuthn einmalig pro Test-Session."""
    os.environ["X2FA_SECRET"] = TEST_SECRET
    os.environ["X2FA_DOMAIN"] = TEST_DOMAIN
    os.environ["X2FA_DATABASE_URL"] = "sqlite:///:memory:"

    from app.services.crypto import CryptoService
    from webauthn_helpers import init_webauthn

    CryptoService(TEST_SECRET)
    init_webauthn(TEST_DOMAIN)


class TestClient:
    """Wrapper um Flask-Testclient mit OIDC-Session-Unterstützung."""

    def __init__(self, flask_app):
        self._app = flask_app
        self._client = flask_app.test_client()

    def app_context(self):
        """App-Context für DB-Operationen außerhalb von Requests."""
        return self._app.app_context()

    def set_session(self, user_id: str = "user_test", setup_mode: bool = False):
        """Setzt eine gültige OIDC-Session vor dem nächsten Request."""
        oidc_req = _OIDC_REQUEST_VERIFY.copy()
        oidc_req["login_hint"] = user_id
        if setup_mode:
            oidc_req["scope"] = "openid x2fa:setup"
        with self._client.session_transaction() as sess:
            sess["oidc_request"] = oidc_req
            sess["user_id"] = user_id
            sess["2fa_verified"] = False
            sess["setup_mode"] = setup_mode

    def _extract(self, response):
        status  = response.status          # e.g. "200 OK" oder "302 FOUND"
        headers = dict(response.headers)
        body    = response.data
        return status, headers, body

    def get(self, path: str, query: str = ""):
        url = f"{path}?{query}" if query else path
        return self._extract(self._client.get(url))

    def post_form(self, path: str, data: dict):
        return self._extract(self._client.post(path, data=data))

    def post_json(self, path: str, data: dict):
        return self._extract(self._client.post(path, json=data))


@pytest.fixture
def client():
    from app import create_app
    flask_app = create_app("testing")
    import app.routes.backup
    app.routes.backup._backup_attempts.clear()
    return TestClient(flask_app)
