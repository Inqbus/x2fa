"""Shared fixtures for X2FA Playwright E2E tests."""

import base64
import hashlib
import http.server
import json
import os
import queue
import secrets
import sys
import threading
import urllib.parse

import pytest
from playwright.sync_api import Page

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "vendor"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Use environment variables or default values
_HOST = os.environ.get("E2E_HOST", "127.0.0.1")
_PORT = int(os.environ.get("E2E_PORT", "5098"))
_TEST_SECRET = "a" * 32
_CLIENT_ID = "e2e-client"
_CLIENT_SECRET = "e2e-secret"

# Dynamically determine callback port
_CALLBACK_PORT = int(os.environ.get("E2E_CALLBACK_PORT", "19999"))
_REDIRECT_URI = f"http://{_HOST}:{_CALLBACK_PORT}/callback"

# Pre-computed PKCE pair (verifier only needed at /token, which we don't call)
_CODE_VERIFIER = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
_CODE_CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(_CODE_VERIFIER.encode()).digest())
    .rstrip(b"=")
    .decode()
)

_BASE_OIDC_REQUEST = {
    "client_id": _CLIENT_ID,
    "redirect_uri": _REDIRECT_URI,
    "scope": "openid",
    "state": "e2estate",
    "nonce": "e2enonce",
    "code_challenge": _CODE_CHALLENGE,
    "code_challenge_method": "S256",
    "response_type": "code",
    "login_hint": "e2e-user",
    "ui_locales": "",
}


# ---------------------------------------------------------------------------
# App + live server (session-scoped — one server for the whole test run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def x2fa_app():
    """Flask app in 'e2e' mode with StaticPool DB, a signing key, and a test client."""
    os.environ["X2FA_SECRET"] = _TEST_SECRET
    os.environ["X2FA_DOMAIN"] = "localhost"

    from app import create_app
    from app.extensions import db
    from app.models import OIDCClient, SigningKey
    from app.services.crypto import CryptoService

    flask_app = create_app("e2e")

    with flask_app.app_context():
        # EC signing key for ID tokens
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )

        crypto = CryptoService(flask_app.config["X2FA_SECRET"])
        priv = ec.generate_private_key(ec.SECP256R1())
        priv_pem = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
        pub_pem = (
            priv.public_key()
            .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )

        db.session.add(
            SigningKey(
                kid=secrets.token_hex(8),
                private_key_encrypted=crypto.get_fernet().encrypt(priv_pem),
                public_key_pem=pub_pem,
                algorithm="ES256",
                active=True,
            )
        )

        # OIDC test client
        db.session.add(
            OIDCClient(
                client_id=_CLIENT_ID,
                client_secret=_CLIENT_SECRET,
                redirect_uris=_REDIRECT_URI,
                allowed_scopes="openid x2fa:setup",
            )
        )
        db.session.commit()

    return flask_app


@pytest.fixture(scope="session")
def live_server(x2fa_app):
    """Starts the X2FA Flask app on _PORT in a background thread."""
    from werkzeug.serving import make_server

    server = make_server(_HOST, _PORT, x2fa_app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://{_HOST}:{_PORT}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Session injection helper
# ---------------------------------------------------------------------------


def _encode(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


@pytest.fixture
def goto_with_session(page: Page, live_server: str):
    """Navigate to a URL with a valid OIDC session already injected.

    Usage:
        goto_with_session("/totp/verify")
        goto_with_session("/totp/setup", setup_mode=True)
        goto_with_session("/totp/verify", user_id="alice", ui_locales="de")
    """

    def _goto(
        path: str,
        *,
        user_id: str = "e2e-user",
        setup_mode: bool = False,
        ui_locales: str = "",
    ):
        # Use a unique nonce per call to prevent AuthorizationCode replay conflicts
        # between tests that all share the same in-memory DB.
        unique_nonce = secrets.token_urlsafe(12)
        oidc_req = {
            **_BASE_OIDC_REQUEST,
            "login_hint": user_id,
            "ui_locales": ui_locales,
            "nonce": unique_nonce,
        }
        if setup_mode:
            oidc_req["scope"] = "openid x2fa:setup"
        session_data = {
            "oidc_request": oidc_req,
            "user_id": user_id,
            "2fa_verified": False,
            "setup_mode": setup_mode,
        }
        encoded = _encode(session_data)
        next_enc = urllib.parse.quote(path, safe="/?=&")
        page.goto(f"{live_server}/test/session?d={encoded}&next={next_enc}")

    return _goto


# ---------------------------------------------------------------------------
# DB fixture helpers (manipulate DB directly via app context)
# ---------------------------------------------------------------------------


@pytest.fixture
def create_totp(x2fa_app):
    """Create a verified TOTP secret for a user_id. Returns the plaintext secret."""

    def _create(user_id: str, totp_secret: str | None = None) -> str:
        import pyotp
        from app.extensions import db
        from app.models import TOTPSecret
        from app.services.crypto import CryptoService

        if totp_secret is None:
            totp_secret = pyotp.random_base32()

        with x2fa_app.app_context():
            crypto = CryptoService(x2fa_app.config["X2FA_SECRET"])
            enc = crypto.encrypt(totp_secret)

            existing = db.session.get(TOTPSecret, user_id)
            if existing:
                existing.secret_encrypted = enc
                existing.verified = True
                existing.last_used_at = None
            else:
                db.session.add(
                    TOTPSecret(user_id=user_id, secret_encrypted=enc, verified=True)
                )
            db.session.commit()

        return totp_secret

    return _create


@pytest.fixture
def create_backup_codes(x2fa_app):
    """Create backup codes for a user_id. Returns the list of plaintext codes."""

    def _create(user_id: str, codes: list[str] | None = None) -> list[str]:
        from app.extensions import db
        from app.models import BackupCode
        from app.services.crypto import CryptoService

        if codes is None:
            codes = [secrets.token_hex(4).upper() for _ in range(10)]

        with x2fa_app.app_context():
            BackupCode.query.filter_by(user_id=user_id).delete()
            for code in codes:
                db.session.add(
                    BackupCode(
                        code_hash=CryptoService.hash_backup_code(code),
                        user_id=user_id,
                    )
                )
            db.session.commit()

        return codes

    return _create


# ---------------------------------------------------------------------------
# Callback URL capture helper
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def callback_server():
    """A minimal HTTP server on port 19999 that captures OIDC callback URLs.

    Runs for the whole test session. Each call to .capture() blocks until the
    next request arrives (or a timeout expires) and returns the full request URL.
    """
    _queue: queue.Queue = queue.Queue()

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            _queue.put(f"http://{_HOST}:{_CALLBACK_PORT}{self.path}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *_):
            pass  # silence access log

    srv = http.server.HTTPServer((_HOST, _CALLBACK_PORT), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    class _Capture:
        def capture(self, timeout: float = 6.0) -> str:
            try:
                return _queue.get(timeout=timeout)
            except queue.Empty:
                raise AssertionError(
                    f"No OIDC callback received on port {_CALLBACK_PORT} within {timeout} s"
                )

    yield _Capture()
    srv.shutdown()


@pytest.fixture
def capture_callback(page: Page, callback_server):
    """Execute an action and return the OIDC callback URL sent to 127.0.0.1:19999.

    The callback_server fixture runs a real HTTP server on port 19999, so when
    X2FA redirects the browser there after successful 2FA, the server captures
    the URL (which contains the authorization code).

    Usage:
        url = capture_callback(lambda: page.click("button[type='submit']"))
        assert "code=" in url
    """

    def _capture(action) -> str:
        action()
        return callback_server.capture(timeout=6.0)

    return _capture
