"""Tests for the extended token-endpoint authentication methods (Options B, C, E).

Covers:
  - authenticate_via_self_signed_tls   (Option B)
  - authenticate_via_client_secret_jwt  (Option C)
  - authenticate_via_client_secret_post (Option E)
  - authenticate_via_client_secret_basic (Option E)
"""

import base64
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import pytest
import jwt as pyjwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from flask import g

from x2fa.app import create_app
from x2fa.constants import (
    AUTH_METHOD_TLS_CLIENT_AUTH,
    AUTH_METHOD_SELF_SIGNED_TLS,
    AUTH_METHOD_CLIENT_SECRET_JWT,
    AUTH_METHOD_CLIENT_SECRET_POST,
    AUTH_METHOD_CLIENT_SECRET_BASIC,
    JWT_BEARER_ASSERTION_TYPE,
)
from x2fa.init_app.database import db
from x2fa.model import OIDCClient
from x2fa.oidc.grants import (
    authenticate_via_self_signed_tls,
    authenticate_via_client_secret_jwt,
    authenticate_via_client_secret_post,
    authenticate_via_client_secret_basic,
)
from x2fa.services.crypto import CryptoService


TOKEN_URL = "https://example.com/token"
SECRET_KEY = "test-secret-key-for-testing-only-32chars"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, headers=None, form=None):
        self.headers = headers or {}
        self.form = form or {}


def _open_ctx():
    ctx = create_app().test_request_context()
    ctx.push()
    g.db_session = db._Session()
    return ctx


def _close_ctx(ctx):
    g.db_session.close()
    ctx.pop()


def _query_client(client_id):
    from sqlalchemy import select
    return g.db_session.execute(
        select(OIDCClient).where(
            OIDCClient.client_id == client_id, OIDCClient.active == True
        )
    ).scalars().first()


def _make_self_signed_cert(cn="test-client"):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    fingerprint = cert.fingerprint(hashes.SHA256()).hex(":")
    return key, cert, cert_pem, fingerprint


def _register_client(client_id, method, **kwargs):
    with create_app().app_context():
        with db.session_scope() as session:
            session.add(OIDCClient(
                client_id=client_id,
                redirect_uris="https://rp/cb",
                token_endpoint_auth_method=method,
                **kwargs,
            ))


def _get_crypto():
    app = create_app()
    with app.app_context():
        return CryptoService(app.config.x2fa_security.SECRET_KEY)


# ---------------------------------------------------------------------------
# Option B — self_signed_tls_client_auth
# ---------------------------------------------------------------------------

class TestSelfSignedTlsAuth:

    def test_valid_fingerprint_returns_client(self):
        _, _, cert_pem, fingerprint = _make_self_signed_cert()
        client_id = "ss-valid"
        _register_client(
            client_id, AUTH_METHOD_SELF_SIGNED_TLS,
            client_cert_fingerprint=fingerprint,
        )

        req = _FakeRequest(headers={"X-Client-Certificate": quote(cert_pem)})
        ctx = _open_ctx()
        try:
            client = authenticate_via_self_signed_tls(_query_client, req)
            assert client is not None
            assert client.client_id == client_id
        finally:
            _close_ctx(ctx)

    def test_no_header_returns_none(self):
        req = _FakeRequest()
        ctx = _open_ctx()
        try:
            assert authenticate_via_self_signed_tls(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_wrong_fingerprint_returns_none(self):
        """A valid cert whose fingerprint is not in the DB returns None."""
        _, _, cert_pem, _ = _make_self_signed_cert()
        req = _FakeRequest(headers={"X-Client-Certificate": quote(cert_pem)})
        ctx = _open_ctx()
        try:
            assert authenticate_via_self_signed_tls(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_wrong_method_returns_none(self):
        """Fingerprint matches but client uses a different auth method — returns None."""
        _, _, cert_pem, fingerprint = _make_self_signed_cert()
        client_id = "ss-wrong-method"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_POST,
            client_cert_fingerprint=fingerprint,
        )
        req = _FakeRequest(headers={"X-Client-Certificate": quote(cert_pem)})
        ctx = _open_ctx()
        try:
            assert authenticate_via_self_signed_tls(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_invalid_pem_returns_none(self):
        req = _FakeRequest(headers={"X-Client-Certificate": "not-a-cert"})
        ctx = _open_ctx()
        try:
            assert authenticate_via_self_signed_tls(_query_client, req) is None
        finally:
            _close_ctx(ctx)


# ---------------------------------------------------------------------------
# Option C — client_secret_jwt
# ---------------------------------------------------------------------------

class TestClientSecretJwtAuth:

    def _encrypt_secret(self, plaintext: str) -> bytes:
        return _get_crypto().encrypt(plaintext)

    def _make_assertion(self, client_id, secret, token_url=TOKEN_URL):
        now = int(time.time())
        return pyjwt.encode(
            {
                "iss": client_id,
                "sub": client_id,
                "aud": token_url,
                "exp": now + 60,
                "iat": now,
                "jti": base64.urlsafe_b64encode(str(now).encode()).decode(),
            },
            secret.encode(),
            algorithm="HS256",
        )

    def test_valid_assertion_returns_client(self):
        plaintext = "a" * 64
        client_id = "csj-valid"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_JWT,
            client_secret_encrypted=self._encrypt_secret(plaintext),
        )

        app = create_app()
        with app.app_context():
            domain = app.config.x2fa.DOMAIN
        token_url = f"https://{domain}/token"
        assertion = self._make_assertion(client_id, plaintext, token_url)

        req = _FakeRequest(form={
            "client_assertion": assertion,
            "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
        })
        ctx = _open_ctx()
        try:
            client = authenticate_via_client_secret_jwt(_query_client, req)
            assert client is not None
            assert client.client_id == client_id
        finally:
            _close_ctx(ctx)

    def test_wrong_secret_returns_none(self):
        plaintext = "b" * 64
        client_id = "csj-wrong-secret"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_JWT,
            client_secret_encrypted=self._encrypt_secret(plaintext),
        )
        assertion = self._make_assertion(client_id, "wrong-secret")
        req = _FakeRequest(form={
            "client_assertion": assertion,
            "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
        })
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_jwt(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_missing_jti_returns_none(self):
        plaintext = "c" * 64
        client_id = "csj-no-jti"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_JWT,
            client_secret_encrypted=self._encrypt_secret(plaintext),
        )
        app = create_app()
        with app.app_context():
            domain = app.config.x2fa.DOMAIN
        token_url = f"https://{domain}/token"
        now = int(time.time())
        # No jti claim
        assertion = pyjwt.encode(
            {"iss": client_id, "sub": client_id, "aud": token_url,
             "exp": now + 60, "iat": now},
            plaintext.encode(), algorithm="HS256",
        )
        req = _FakeRequest(form={
            "client_assertion": assertion,
            "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
        })
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_jwt(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_no_assertion_returns_none(self):
        req = _FakeRequest(form={})
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_jwt(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_wrong_assertion_type_returns_none(self):
        req = _FakeRequest(form={
            "client_assertion": "anything",
            "client_assertion_type": "wrong:type",
        })
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_jwt(_query_client, req) is None
        finally:
            _close_ctx(ctx)


# ---------------------------------------------------------------------------
# Option E — client_secret_post
# ---------------------------------------------------------------------------

class TestClientSecretPostAuth:

    def _encrypt(self, plaintext: str) -> bytes:
        return _get_crypto().encrypt(plaintext)

    def test_valid_secret_returns_client(self):
        plaintext = "post-secret-" + "x" * 52
        client_id = "csp-valid"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_POST,
            client_secret_encrypted=self._encrypt(plaintext),
        )
        req = _FakeRequest(form={"client_id": client_id, "client_secret": plaintext})
        ctx = _open_ctx()
        try:
            client = authenticate_via_client_secret_post(_query_client, req)
            assert client is not None
            assert client.client_id == client_id
        finally:
            _close_ctx(ctx)

    def test_wrong_secret_returns_none(self):
        plaintext = "post-secret-right"
        client_id = "csp-wrong"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_POST,
            client_secret_encrypted=self._encrypt(plaintext),
        )
        req = _FakeRequest(form={"client_id": client_id, "client_secret": "wrong"})
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_post(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_missing_fields_returns_none(self):
        req = _FakeRequest(form={"client_id": "someone"})
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_post(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_wrong_method_returns_none(self):
        """Client registered for tls_client_auth — secret_post must not match."""
        plaintext = "post-secret-method-mismatch"
        client_id = "csp-method-mismatch"
        _register_client(
            client_id, AUTH_METHOD_TLS_CLIENT_AUTH,
            client_secret_encrypted=self._encrypt(plaintext),
        )
        req = _FakeRequest(form={"client_id": client_id, "client_secret": plaintext})
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_post(_query_client, req) is None
        finally:
            _close_ctx(ctx)


# ---------------------------------------------------------------------------
# Option E — client_secret_basic
# ---------------------------------------------------------------------------

class TestClientSecretBasicAuth:

    def _encrypt(self, plaintext: str) -> bytes:
        return _get_crypto().encrypt(plaintext)

    def _basic_header(self, client_id, client_secret):
        credentials = base64.b64encode(
            f"{client_id}:{client_secret}".encode()
        ).decode()
        return f"Basic {credentials}"

    def test_valid_credentials_returns_client(self):
        plaintext = "basic-secret-" + "y" * 51
        client_id = "csb-valid"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_BASIC,
            client_secret_encrypted=self._encrypt(plaintext),
        )
        req = _FakeRequest(
            headers={"Authorization": self._basic_header(client_id, plaintext)}
        )
        ctx = _open_ctx()
        try:
            client = authenticate_via_client_secret_basic(_query_client, req)
            assert client is not None
            assert client.client_id == client_id
        finally:
            _close_ctx(ctx)

    def test_wrong_secret_returns_none(self):
        plaintext = "basic-secret-right"
        client_id = "csb-wrong"
        _register_client(
            client_id, AUTH_METHOD_CLIENT_SECRET_BASIC,
            client_secret_encrypted=self._encrypt(plaintext),
        )
        req = _FakeRequest(
            headers={"Authorization": self._basic_header(client_id, "wrong")}
        )
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_basic(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_no_auth_header_returns_none(self):
        req = _FakeRequest()
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_basic(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_bearer_header_not_basic_returns_none(self):
        req = _FakeRequest(headers={"Authorization": "Bearer sometoken"})
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_basic(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_malformed_base64_returns_none(self):
        req = _FakeRequest(headers={"Authorization": "Basic not!valid!base64!!!"})
        ctx = _open_ctx()
        try:
            assert authenticate_via_client_secret_basic(_query_client, req) is None
        finally:
            _close_ctx(ctx)
