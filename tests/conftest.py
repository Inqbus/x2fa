"""Gemeinsame Fixtures für alle X2FA-Tests."""

import io
import os
import sys

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

    # SQLAlchemy-Engine neu erstellen damit die In-Memory-URL greift
    import models
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    models.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.SessionLocal = sessionmaker(bind=models.engine)

    from crypto import init_crypto
    from webauthn_helpers import init_webauthn
    from audit import init_audit
    from models import init_db

    init_crypto(TEST_SECRET)
    init_webauthn(TEST_DOMAIN)
    init_audit(TEST_SECRET)
    init_db()


@pytest.fixture(autouse=True)
def clean_db():
    """Leert alle Tabellen vor jedem Test."""
    from models import SessionLocal, Credential, Challenge, TOTPSecret, BackupCode, AuditLog
    with SessionLocal() as db:
        db.query(AuditLog).delete()
        db.query(BackupCode).delete()
        db.query(TOTPSecret).delete()
        db.query(Challenge).delete()
        db.query(Credential).delete()
        db.commit()


class TestClient:
    """Minimaler WSGI-Client für Bottle-Tests."""

    def __init__(self, app):
        self.app = app

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
    from x2fa import app
    # Rate-Limiter vor jedem Test zurücksetzen
    import x2fa
    x2fa._backup_attempts.clear()
    return TestClient(app)


@pytest.fixture
def setup_token():
    from crypto import create_jwt
    return create_jwt({"sub": "user_test", "action": "setup", "return_url": "https://app/cb"}, 5)


@pytest.fixture
def verify_token():
    from crypto import create_jwt
    return create_jwt({"sub": "user_test", "action": "verify", "return_url": "https://app/cb"}, 5)
