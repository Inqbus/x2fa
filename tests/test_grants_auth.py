"""Tests for the new token-endpoint authentication methods (Step 5).

Tests authenticate_via_mtls() and X2FAPrivateKeyJwtAuth directly,
using a minimal fake request object and a real Flask app context with DB.
"""

import base64
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from authlib.oauth2.rfc6749 import InvalidClientError
from authlib.jose import jwt as jose_jwt

from flask import g

from x2fa.app import create_app
from x2fa.constants import (
    AUTH_METHOD_PRIVATE_KEY_JWT,
    AUTH_METHOD_TLS_CLIENT_AUTH,
    JWT_BEARER_ASSERTION_TYPE,
)
from x2fa.init_app.database import db
from x2fa.model import OIDCClient, TrustedCA
from x2fa.oidc.grants import authenticate_via_mtls, X2FAPrivateKeyJwtAuth

from tests.conftest import make_ec_ca, make_client_cert


TOKEN_URL = "https://example.com/token"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeRequest:
    """Minimal stand-in for an OAuth2Request — only headers and form are used."""

    def __init__(self, headers=None, form=None):
        self.headers = headers or {}
        self.form = form or {}
        self.client = None  # set by JWTBearerClientAssertion.create_resolve_key_func


def _open_ctx():
    """Enters a test request context with g.db_session already set."""
    ctx = create_app().test_request_context()
    ctx.push()
    g.db_session = db._Session()
    return ctx


def _close_ctx(ctx):
    g.db_session.close()
    ctx.pop()


def _register_ca_and_client(ca_pem, client_id, method):
    """Inserts a TrustedCA and an OIDCClient directly via session_scope."""
    with create_app().app_context():
        with db.session_scope() as session:
            session.add(TrustedCA(name=f"ca-{client_id}", cert_pem=ca_pem))
            session.add(OIDCClient(
                client_id=client_id,

                redirect_uris="https://rp/cb",
                token_endpoint_auth_method=method,
            ))


def _query_client(client_id):
    """query_client callable using the request-scoped g.db_session."""
    from sqlalchemy import select
    return g.db_session.execute(
        select(OIDCClient).where(OIDCClient.client_id == client_id, OIDCClient.active == True)
    ).scalars().first()


def _make_client_key_and_cert(cn, ca_key, ca_cert):
    """Returns (client_key, client_cert, cert_pem) for a fresh EC client certificate."""
    client_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=90))
        .sign(ca_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return client_key, cert, cert_pem


def _make_jwt_with_x5c(client_key, client_cert, client_id, token_url):
    """Returns a signed JWT with the client cert embedded as x5c in the header."""
    from authlib.jose import JsonWebKey

    cert_der = client_cert.public_bytes(serialization.Encoding.DER)
    x5c = [base64.b64encode(cert_der).decode()]
    now = int(time.time())
    payload = {
        "iss": client_id,
        "sub": client_id,
        "aud": token_url,
        "exp": now + 60,
        "iat": now,
        "jti": base64.urlsafe_b64encode(str(now).encode()).decode(),
    }
    key_pem = client_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    jwk = JsonWebKey.import_key(key_pem)
    token = jose_jwt.encode({"alg": "ES256", "x5c": x5c}, payload, jwk)
    return token.decode() if isinstance(token, bytes) else token


# ---------------------------------------------------------------------------
# authenticate_via_mtls
# ---------------------------------------------------------------------------

class TestMtlsAuth:

    def test_valid_cert_returns_client(self):
        """A valid cert signed by a registered CA returns the matching OIDCClient."""
        ca_key, ca_cert, ca_pem = make_ec_ca("mtls-ca-1")
        client_id = "rp-mtls-valid"
        _register_ca_and_client(ca_pem, client_id, AUTH_METHOD_TLS_CLIENT_AUTH)

        cert_pem = make_client_cert(client_id, ca_key, ca_cert)
        req = _FakeRequest(headers={"X-Client-Certificate": quote(cert_pem)})

        ctx = _open_ctx()
        try:
            client = authenticate_via_mtls(_query_client, req)
            assert client is not None
            assert client.client_id == client_id
        finally:
            _close_ctx(ctx)

    def test_no_header_returns_none(self):
        """Returns None when the X-Client-Certificate header is absent."""
        req = _FakeRequest()

        ctx = _open_ctx()
        try:
            assert authenticate_via_mtls(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_untrusted_cert_returns_none(self):
        """Returns None when the cert is signed by an unregistered CA."""
        ca_key, ca_cert, _ = make_ec_ca("unknown-ca")
        cert_pem = make_client_cert("rp-mtls-untrusted", ca_key, ca_cert)
        req = _FakeRequest(headers={"X-Client-Certificate": quote(cert_pem)})

        ctx = _open_ctx()
        try:
            assert authenticate_via_mtls(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_expired_client_cert_returns_none(self):
        """Returns None when the client certificate is expired."""
        ca_key, ca_cert, ca_pem = make_ec_ca("mtls-ca-expiry")
        client_id = "rp-mtls-expired"
        _register_ca_and_client(ca_pem, client_id, AUTH_METHOD_TLS_CLIENT_AUTH)

        now = datetime.now(timezone.utc)
        expired_cert = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, client_id)]))
            .issuer_name(ca_cert.subject)
            .public_key(ec.generate_private_key(ec.SECP256R1()).public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=2))
            .not_valid_after(now - timedelta(days=1))
            .sign(ca_key, hashes.SHA256())
        )
        cert_pem = expired_cert.public_bytes(serialization.Encoding.PEM).decode()
        req = _FakeRequest(headers={"X-Client-Certificate": quote(cert_pem)})

        ctx = _open_ctx()
        try:
            assert authenticate_via_mtls(_query_client, req) is None
        finally:
            _close_ctx(ctx)

    def test_cert_cn_not_in_db_returns_none(self):
        """Returns None when the cert is trusted but the CN has no registered client."""
        ca_key, ca_cert, ca_pem = make_ec_ca("mtls-ca-no-client")
        with create_app().app_context():
            with db.session_scope() as session:
                session.add(TrustedCA(name="ca-no-client", cert_pem=ca_pem))

        cert_pem = make_client_cert("nonexistent-client", ca_key, ca_cert)
        req = _FakeRequest(headers={"X-Client-Certificate": quote(cert_pem)})

        ctx = _open_ctx()
        try:
            assert authenticate_via_mtls(_query_client, req) is None
        finally:
            _close_ctx(ctx)


# ---------------------------------------------------------------------------
# X2FAPrivateKeyJwtAuth — x5c flow
# ---------------------------------------------------------------------------

class TestPrivateKeyJwtX5c:

    def _auth(self):
        return X2FAPrivateKeyJwtAuth(TOKEN_URL)

    def test_valid_x5c_jwt_returns_client(self):
        """A JWT with a trusted x5c cert and valid signature returns the client."""
        ca_key, ca_cert, ca_pem = make_ec_ca("jwt-ca-1")
        client_id = "rp-jwt-valid"
        _register_ca_and_client(ca_pem, client_id, AUTH_METHOD_PRIVATE_KEY_JWT)

        client_key, client_cert, _ = _make_client_key_and_cert(client_id, ca_key, ca_cert)
        token = _make_jwt_with_x5c(client_key, client_cert, client_id, TOKEN_URL)
        req = _FakeRequest(form={
            "client_assertion": token,
            "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
        })

        ctx = _open_ctx()
        try:
            client = self._auth()(_query_client, req)
            assert client is not None
            assert client.client_id == client_id
        finally:
            _close_ctx(ctx)

    def test_x5c_cert_not_trusted_raises(self):
        """Raises InvalidClientError when the x5c cert is signed by an unknown CA."""
        ca_key, ca_cert, _ = make_ec_ca("unknown-jwt-ca")
        client_id = "rp-jwt-untrusted"
        # Register the client but NOT the CA
        with create_app().app_context():
            with db.session_scope() as session:
                session.add(OIDCClient(
                    client_id=client_id,
    
                    redirect_uris="https://rp/cb",
                    token_endpoint_auth_method=AUTH_METHOD_PRIVATE_KEY_JWT,
                ))

        client_key, client_cert, _ = _make_client_key_and_cert(client_id, ca_key, ca_cert)
        token = _make_jwt_with_x5c(client_key, client_cert, client_id, TOKEN_URL)
        req = _FakeRequest(form={
            "client_assertion": token,
            "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
        })

        ctx = _open_ctx()
        try:
            with pytest.raises(InvalidClientError):
                self._auth()(_query_client, req)
        finally:
            _close_ctx(ctx)

    def test_no_x5c_and_no_jwks_uri_raises(self):
        """Raises InvalidClientError when there is no x5c and the client has no jwks_uri."""
        ca_key, ca_cert, ca_pem = make_ec_ca("jwt-ca-nokey")
        client_id = "rp-jwt-no-key"
        _register_ca_and_client(ca_pem, client_id, AUTH_METHOD_PRIVATE_KEY_JWT)

        client_key, _, _ = _make_client_key_and_cert(client_id, ca_key, ca_cert)

        from authlib.jose import JsonWebKey
        now = int(time.time())
        payload = {
            "iss": client_id, "sub": client_id, "aud": TOKEN_URL,
            "exp": now + 60, "iat": now,
        }
        key_pem = client_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        jwk = JsonWebKey.import_key(key_pem)
        # JWT without x5c in header
        token = jose_jwt.encode({"alg": "ES256"}, payload, jwk)
        token_str = token.decode() if isinstance(token, bytes) else token
        req = _FakeRequest(form={
            "client_assertion": token_str,
            "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
        })

        ctx = _open_ctx()
        try:
            with pytest.raises(InvalidClientError):
                self._auth()(_query_client, req)
        finally:
            _close_ctx(ctx)

    def test_wrong_auth_method_raises(self):
        """Raises InvalidClientError when client is registered for tls_client_auth, not private_key_jwt."""
        ca_key, ca_cert, ca_pem = make_ec_ca("jwt-ca-wrong-method")
        client_id = "rp-jwt-wrong-method"
        _register_ca_and_client(ca_pem, client_id, AUTH_METHOD_TLS_CLIENT_AUTH)

        client_key, client_cert, _ = _make_client_key_and_cert(client_id, ca_key, ca_cert)
        token = _make_jwt_with_x5c(client_key, client_cert, client_id, TOKEN_URL)
        req = _FakeRequest(form={
            "client_assertion": token,
            "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
        })

        ctx = _open_ctx()
        try:
            with pytest.raises(InvalidClientError):
                self._auth()(_query_client, req)
        finally:
            _close_ctx(ctx)
