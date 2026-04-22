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


# ---------------------------------------------------------------------------
# Constants — read from settings.toml [e2e] section via x2fa_settings
# ---------------------------------------------------------------------------

REDIRECT_URI = f"http://{app.configure.x2fa.HOST}:{app.configure.x2fa.CALLBACK_PORT}/callback"

# Pre-computed PKCE challenge (verifier only needed at /token, which we don't call)
CODE_CHALLENGE = (
    base64.urlsafe_b64encode(
        hashlib.sha256("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM".encode()).digest()
    )
    .rstrip(b"=")
    .decode()
)

BASE_OIDC_REQUEST = {
    "client_id": app.configure.x2fa_security.CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
    "scope": "openid",
    "state": "e2estate",
    "nonce": "e2enonce",
    "code_challenge": CODE_CHALLENGE,
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
    os.environ["X2FA_SECRET"] = "a" * 32
    os.environ["X2FA_DOMAIN"] = app.configure.x2fa.DOMAIN

    from x2fa.app import create_app
    from x2fa.models import OIDCClient, SigningKey
    from x2fa.services.crypto import CryptoService
    from x2fa.init_app.database import db

    flask_app = create_app()

    with flask_app.app_context():
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )

        with db.test_transaction() as db_session:
            priv = ec.generate_private_key(ec.SECP256R1())
            db_session.add(
                SigningKey(
                    kid=secrets.token_hex(8),
                    private_key_encrypted=CryptoService(
                        flask_app.config.x2fa_security.SECRET_KEY
                    )
                    .get_fernet()
                    .encrypt(
                        priv.private_bytes(
                            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
                        )
                    ),
                    public_key_pem=priv.public_key()
                    .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
                    .decode(),
                    algorithm="ES256",
                    active=True,
                )
            )

            # OIDC test client
            db_session.add(
                OIDCClient(
                    client_id=app.configure.x2fa_security.CLIENT_ID,
                    client_secret=app.configure.x2fa_security.CLIENT_SECRET,
                    redirect_uris=REDIRECT_URI,
                    allowed_scopes="openid app:setup",
                )
            )

    return flask_app


@pytest.fixture(scope="session")
def x2fa_server(x2fa_app):
    """Starts the X2FA Flask app on app.config.x2fa.PORT in a background thread."""
    from werkzeug.serving import make_server

    server = make_server(app.configure.x2fa.HOST, app.configure.x2fa.PORT, x2fa_app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://{app.configure.x2fa.HOST}:{app.configure.x2fa.PORT}"
    server.shutdown()


# ---------------------------------------------------------------------------
# Session injection helper
# ---------------------------------------------------------------------------


def _encode(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


@pytest.fixture
def goto_with_session(page: Page, x2fa_server: str):
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
        oidc_req = {
            **BASE_OIDC_REQUEST,
            "login_hint": user_id,
            "ui_locales": ui_locales,
            "nonce": secrets.token_urlsafe(12),
        }
        if setup_mode:
            oidc_req["scope"] = "openid app:setup"
        page.goto(
            f"{x2fa_server}/test/session"
            f"?d={_encode({'oidc_request': oidc_req, 'user_id': user_id, '2fa_verified': False, 'setup_mode': setup_mode})}"
            f"&next={urllib.parse.quote(path, safe='/?=&')}"
        )

    return _goto


# ---------------------------------------------------------------------------
# DB fixture helpers (manipulate DB directly via app context)
# ---------------------------------------------------------------------------


@pytest.fixture
def create_totp(x2fa_app):
    """Create a verified TOTP secret for a user_id. Returns the plaintext secret."""

    def _create(user_id: str, totp_secret: str | None = None) -> str:
        import pyotp
        from x2fa.models import TOTPSecret
        from x2fa.services.crypto import CryptoService
        from x2fa.constants import NEVER_USED
        from x2fa.init_app.database import db

        if totp_secret is None:
            totp_secret = pyotp.random_base32()

        with x2fa_app.app_context():
            with db.test_transaction() as db_session:
                crypto = CryptoService(x2fa_app.config.x2fa_security.SECRET_KEY)
                enc = crypto.encrypt(totp_secret)

                existing = db_session.get(TOTPSecret, user_id)
                if existing:
                    existing.secret_encrypted = enc
                    existing.verified = True
                    existing.last_used_at = NEVER_USED
                else:
                    db_session.add(
                        TOTPSecret(user_id=user_id, secret_encrypted=enc, verified=True)
                    )

        return totp_secret

    return _create


@pytest.fixture
def create_backup_codes(x2fa_app):
    """Create backup codes for a user_id. Returns the list of plaintext codes."""

    def _create(user_id: str, codes: list[str] | None = None) -> list[str]:
        from sqlalchemy import delete
        from x2fa.models import BackupCode
        from x2fa.services.crypto import CryptoService
        from x2fa.init_app.database import db

        if codes is None:
            codes = [secrets.token_hex(4).upper() for _ in range(10)]

        with x2fa_app.app_context():
            with db.test_transaction() as db_session:
                db_session.execute(
                    delete(BackupCode).where(BackupCode.user_id == user_id)
                )
                for code in codes:
                    db_session.add(
                        BackupCode(
                            code_hash=CryptoService.hash_backup_code(code),
                            user_id=user_id,
                        )
                    )

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
            _queue.put(f"http://{app.configure.x2fa.HOST}:{app.configure.x2fa.CALLBACK_PORT}{self.path}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")

        def log_message(self, *_):
            pass  # silence access log

    srv = http.server.HTTPServer((app.configure.x2fa.HOST, app.configure.x2fa.CALLBACK_PORT), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    class _Capture:
        def capture(self, timeout: float = 6.0) -> str:
            try:
                return _queue.get(timeout=timeout)
            except queue.Empty:
                raise AssertionError(
                    f"No OIDC callback received on port {app.configure.x2fa.CALLBACK_PORT} within {timeout} s"
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
