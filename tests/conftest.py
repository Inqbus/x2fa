"""Gemeinsame Fixtures für alle X2FA-Tests."""

import io
import os
import sys
import time

import pytest

# Projektverzeichnis in sys.path damit alle Module gefunden werden
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vendor"))

TEST_SECRET = "a" * 32
TEST_DOMAIN = "test.example.com"


@pytest.fixture(scope="session", autouse=True)
def init_services():
    """Initialisiert Crypto, WebAuthn und In-Memory-DB einmalig pro Test-Session."""
    os.environ["X2FA_SECRET"] = TEST_SECRET
    os.environ["X2FA_DOMAIN"] = TEST_DOMAIN
    os.environ["X2FA_DATABASE_URL"] = "sqlite:///:memory:"

    from app.services.crypto import CryptoService
    from webauthn_helpers import init_webauthn
    
    crypto = CryptoService(TEST_SECRET)
    init_webauthn(TEST_DOMAIN)


# @pytest.fixture(autouse=True)
# def clean_db():
#     """Leert alle Tabellen vor jedem Test."""
#     from app.models import db, Credential, Challenge, TOTPSecret, BackupCode, AuditLog
#     from flask import current_app
#     
#     with current_app.app_context():
#         with db.session() as session:
#             session.query(AuditLog).delete()
#             session.query(BackupCode).delete()
#             session.query(TOTPSecret).delete()
#             session.query(Challenge).delete()
#             session.query(Credential).delete()
#             session.commit()


class TestClient:
    """Minimaler WSGI-Client für Bottle-Tests."""

    def __init__(self, app):
        self.app = app.wsgi_app

    def _call(self, method, path, query="", body=b"", content_type="application/x-www-form-urlencoded"):
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
            "wsgi.errors": io.StringIO(),
            "SERVER_NAME": "localhost",
            "SERVER_PORT": "5000",
            "HTTP_HOST": "localhost:5000",
            "wsgi.url_scheme": "http",
            "REMOTE_ADDR": "127.0.0.1",
        }
        captured = {}
        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body_chunks = list(self.app(environ, start_response))
        return captured["status"], captured["headers"], b"".join(body_chunks)

    def get(self, path, query=""):
        return self._call("GET", path, query=query)

    def post_form(self, path, data: dict):
        from urllib.parse import urlencode
        body = urlencode(data).encode()
        return self._call("POST", path, body=body)

    def post_json(self, path, data: dict):
        import json
        body = json.dumps(data).encode()
        return self._call("POST", path, body=body, content_type="application/json")


@pytest.fixture
def client():
    from app import create_app
    flask_app = create_app("testing")
    # Rate-Limiter vor jedem Test zurücksetzen
    import app.routes.backup
    app.routes.backup._backup_attempts.clear()
    return TestClient(flask_app)


@pytest.fixture
def setup_token():
    """Mock JWT token for TOTP setup flow."""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyX3Rlc3QiLCJhY3Rpb24iOiJzZXR1cCIsInJlZGlydWxlX3VybCI6Imh0dHBzOi8vYXBwL2NicyIsImlhdCI6MTY3NTA5OTU3N30.XCZzXCZzXCZzXCZzXCZzXCZzXCZzXCZzXCZz"  # Mock token


@pytest.fixture
def verify_token():
    """Mock JWT token for TOTP verify flow."""
    return "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyX3Rlc3QiLCJhY3Rpb24iOiJ2ZXJpZmllZCIsInJlZGlydWxlX3VybCI6Imh0dHBzOi8vYXBwL2NicyIsImlhdCI6MTY3NTA5OTU3N30.XCZzXCZzXCZzXCZzXCZzXCZzXCZzXCZzXCZz"  # Mock token
