"""Shared fixtures for all X2FA tests."""

# Must be set before any x2fa import so Dynaconf loads the [testing] section
# from all config files (db_config.toml, security_config.toml, …).
import os

os.environ.setdefault("ENV_FOR_DYNACONF", "testing")

import pytest

from x2fa.app import create_app


TEST_DOMAIN = "test.example.com"

# Default OIDC session for tests (verification flow)
OIDC_REQUEST_VERIFY = {
    "client_id": "test_client",
    "redirect_uri": "https://app/cb",
    "scope": "openid",
    "state": "teststate",
    "nonce": "testnonce",
    "code_challenge": "e3b0c44298fc1c149afbf4c8996fb924",
    "code_challenge_method": "S256",
    "response_type": "code",
    "login_hint": "user_test",
}


class TestClient:
    """Wrapper around the Flask test client with OIDC session support."""

    def __init__(self, flask_app):
        self._app = flask_app
        self._client = flask_app.test_client()

    def app_context(self):
        """App context for DB operations outside of requests."""
        return self._app.app_context()

    def set_session(
        self, user_id: str = "user_test", setup_mode: bool = False, ui_locales: str = ""
    ):
        """Sets a valid OIDC session before the next request."""
        oidc_req = OIDC_REQUEST_VERIFY.copy()
        oidc_req["login_hint"] = user_id
        oidc_req["ui_locales"] = ui_locales
        if setup_mode:
            oidc_req["scope"] = "openid app:setup"
        with self._client.session_transaction() as sess:
            sess["oidc_request"] = oidc_req
            sess["user_id"] = user_id
            sess["2fa_verified"] = False
            sess["setup_mode"] = setup_mode

    def _extract(self, response):
        return response.status, dict(response.headers), response.data

    def get(self, path: str, query: str = ""):
        return self._extract(self._client.get(f"{path}?{query}" if query else path))

    def post_form(self, path: str, data: dict):
        return self._extract(self._client.post(path, data=data))

    def post_json(self, path: str, data: dict):
        return self._extract(self._client.post(path, json=data))


@pytest.fixture
def client():
    flask_app = create_app()

    # Reset the schema before each test so no data leaks between tests.
    from x2fa.models import Base
    from x2fa.init_app.database import get_engine

    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    return TestClient(flask_app)
