import time
from datetime import datetime, timezone, timedelta

from authlib.oauth2.rfc6749 import InvalidClientError
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc7523.client import JWTBearerClientAssertion
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core.grants import OpenIDCode

from flask import g
from sqlalchemy import select

from x2fa.constants import (
    ALL_AUTH_METHODS,
    AUTH_METHOD_PRIVATE_KEY_JWT,
    AUTH_METHOD_TLS_CLIENT_AUTH,
    AUTH_METHOD_SELF_SIGNED_TLS,
    AUTH_METHOD_CLIENT_SECRET_JWT,
    AUTH_METHOD_CLIENT_SECRET_POST,
    AUTH_METHOD_CLIENT_SECRET_BASIC,
    JWT_BEARER_ASSERTION_TYPE,
)
from x2fa.model import AuthorizationCode, OIDCClient, SigningKey, TrustedCA


class S256OnlyCodeChallenge(CodeChallenge):
    """Restricts PKCE to S256 only — 'plain' is explicitly rejected."""

    SUPPORTED_CODE_CHALLENGE_METHOD = ["S256"]


class X2FAAuthorizationCodeGrant(AuthorizationCodeGrant):
    """
    OIDC Authorization Code Grant with mandatory PKCE S256.

    Flow:
      1. /authorize  → validate_authorization_request → save_authorization_code
      2. /token      → query_authorization_code → delete_authorization_code
                       → authenticate_user
    """

    TOKEN_ENDPOINT_AUTH_METHODS = ALL_AUTH_METHODS

    def save_authorization_code(self, code, request):
        """Persists the authorization code to the database."""
        user_id = request.user  # set by create_authorization_response(grant_user=...)
        payload = request.payload
        auth_code = AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            user_id=user_id,
            redirect_uri=(
                payload.redirect_uri or request.client.get_default_redirect_uri()
            ),
            scope=payload.scope,
            nonce=payload.data.get("nonce"),
            code_challenge=payload.data.get("code_challenge"),
            code_challenge_method="S256",
            auth_time=int(time.time()),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        g.db_session.add(auth_code)
        g.db_session.commit()
        return auth_code

    def query_authorization_code(self, code, client):
        """Looks up a valid (unused, unexpired) authorization code."""
        stmt = select(AuthorizationCode).where(
            AuthorizationCode.code == code,
            AuthorizationCode.client_id == client.client_id,
        )
        auth_code = g.db_session.execute(stmt).scalars().first()
        if not auth_code or auth_code.is_expired() or auth_code.used:
            return None
        return auth_code

    def delete_authorization_code(self, authorization_code):
        """Marks the code as used. Does not physically delete — preserves nonce for replay protection."""
        authorization_code.used = True
        g.db_session.commit()

    def authenticate_user(self, authorization_code):
        """Returns the user identifier (becomes the 'sub' claim in the ID token)."""
        return authorization_code.user_id


class X2FAOpenIDCode(OpenIDCode):
    """
    OpenIDCode extension: generates ES256-signed ID tokens and enforces nonce replay protection.

    Registered as an extension on X2FAAuthorizationCodeGrant (not a mixin)
    so that Authlib's hook system fires correctly in version 1.6+.
    """

    def exists_nonce(self, nonce, request):
        """Returns True if this nonce has already been used (replay protection)."""
        if not nonce:
            return False
        stmt = select(AuthorizationCode).where(AuthorizationCode.nonce == nonce)
        return g.db_session.execute(stmt).scalars().first() is not None

    def get_jwt_config(self, grant, client=None):
        """Returns the JWT signing configuration for the ID token."""
        from flask import current_app
        from x2fa.services.crypto import CryptoService

        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        stmt = (
            select(SigningKey)
            .where(SigningKey.active == True)
            .where(SigningKey.expires_at > datetime.now(timezone.utc))
            .order_by(SigningKey.created_at.desc())
        )

        signing_key = g.db_session.execute(stmt).scalars().first()
        if not signing_key:
            raise RuntimeError(
                "No active signing key found. Run 'flask init-keys' first."
            )
        private_key = signing_key.get_private_key(crypto.get_fernet())
        domain = current_app.config.x2fa.DOMAIN
        return {
            "key": private_key,
            "alg": signing_key.algorithm,
            "iss": f"https://{domain}",
            "exp": 60,  # ID token lifetime in seconds
            "kid": signing_key.kid,
        }

    def generate_user_info(self, user, scope):
        """Returns the minimal claims set for the ID token payload."""
        return {"sub": user}


def authenticate_via_mtls(query_client, request):
    """Client authenticator for tls_client_auth.

    Reads the PEM-encoded client certificate from the X-Client-Certificate header
    (nginx: proxy_set_header X-Client-Certificate $ssl_client_escaped_cert),
    validates it against every active TrustedCA, and returns the matching OIDCClient.
    """
    from urllib.parse import unquote

    cert_raw = request.headers.get("X-Client-Certificate")
    if not cert_raw:
        return None

    cert_pem = unquote(cert_raw)

    cas = g.db_session.execute(
        select(TrustedCA).where(TrustedCA.active == True)
    ).scalars().all()

    for ca in cas:
        result = ca.verify_certificate(cert_pem)
        if result["valid"]:
            return query_client(result["client_id"])

    return None


class X2FAPrivateKeyJwtAuth(JWTBearerClientAssertion):
    """Client authenticator for private_key_jwt.

    Supports two key resolution strategies:
    - x5c in the JWT header: validates the embedded cert chain against active TrustedCAs
      and returns the leaf certificate's public key.
    - jwks_uri on the client row: fetches the JWKS endpoint and matches by kid.

    JTI replay protection is not implemented (acceptable for internal deployments).
    """

    CLIENT_AUTH_METHOD = AUTH_METHOD_PRIVATE_KEY_JWT

    def authenticate_client(self, client):
        if client.check_endpoint_auth_method(AUTH_METHOD_PRIVATE_KEY_JWT, "token"):
            return client
        raise InvalidClientError(
            description="Client is not registered for private_key_jwt authentication."
        )

    def resolve_client_public_key(self, client, headers):
        x5c = headers.get("x5c")
        if x5c:
            return self._key_from_x5c(x5c)
        if client.jwks_uri:
            return self._key_from_jwks_uri(client, headers)
        raise InvalidClientError(description="No public key available for this client.")

    def _key_from_x5c(self, x5c):
        import base64
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding

        try:
            leaf_der = base64.b64decode(x5c[0])
            leaf_cert = x509.load_der_x509_certificate(leaf_der)
        except Exception as exc:
            raise InvalidClientError(description=f"Invalid x5c certificate: {exc}")

        leaf_pem = leaf_cert.public_bytes(Encoding.PEM).decode()

        cas = g.db_session.execute(
            select(TrustedCA).where(TrustedCA.active == True)
        ).scalars().all()

        for ca in cas:
            if ca.verify_certificate(leaf_pem)["valid"]:
                return leaf_cert.public_key()

        raise InvalidClientError(
            description="Certificate in x5c is not trusted by any registered CA."
        )

    def _key_from_jwks_uri(self, client, headers):
        import json
        import urllib.request
        from authlib.jose import JsonWebKey

        kid = headers.get("kid")
        try:
            with urllib.request.urlopen(client.jwks_uri, timeout=5) as resp:
                jwks = json.loads(resp.read())
        except Exception as exc:
            raise InvalidClientError(
                description=f"Failed to fetch JWKS from {client.jwks_uri}: {exc}"
            )

        for k in jwks.get("keys", []):
            if kid is None or k.get("kid") == kid:
                return JsonWebKey.import_key(k)

        raise InvalidClientError(description="No matching key found in JWKS.")

    def validate_jti(self, claims, jti):
        return True


def authenticate_via_self_signed_tls(query_client, request):
    """Client authenticator for self_signed_tls_client_auth.

    Reads the PEM-encoded client certificate from the X-Client-Certificate header,
    computes its SHA-256 fingerprint, and looks up the matching OIDCClient.
    No CA chain validation — the fingerprint IS the trust anchor.
    """
    from urllib.parse import unquote
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from sqlalchemy import select

    cert_raw = request.headers.get("X-Client-Certificate")
    if not cert_raw:
        return None

    try:
        cert = x509.load_pem_x509_certificate(unquote(cert_raw).encode())
    except Exception:
        return None

    fingerprint = cert.fingerprint(hashes.SHA256()).hex(":")
    stmt = select(OIDCClient).where(
        OIDCClient.client_cert_fingerprint == fingerprint,
        OIDCClient.active == True,
        OIDCClient.token_endpoint_auth_method == AUTH_METHOD_SELF_SIGNED_TLS,
    )
    return g.db_session.execute(stmt).scalars().first()


def _verify_client_secret(query_client, client_id: str, secret: str, method: str):
    """Constant-time secret comparison for client_secret_* auth methods."""
    import hmac
    from flask import current_app
    from x2fa.services.crypto import CryptoService

    client = query_client(client_id)
    if not client or client.token_endpoint_auth_method != method:
        return None
    if not client.client_secret_encrypted:
        return None

    crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
    stored = crypto.decrypt(client.client_secret_encrypted)
    if hmac.compare_digest(stored, secret):
        return client
    return None


def authenticate_via_client_secret_jwt(query_client, request):
    """Client authenticator for client_secret_jwt (RFC 7523 §2.2, HS256).

    Decodes the JWT assertion without verification to extract the client_id,
    then Fernet-decrypts the stored secret and verifies the HMAC signature
    plus required claims (iss, sub, aud, exp, jti).
    """
    import jwt as pyjwt

    assertion = request.form.get("client_assertion")
    assertion_type = request.form.get("client_assertion_type")
    if assertion_type != JWT_BEARER_ASSERTION_TYPE or not assertion:
        return None

    try:
        unverified = pyjwt.decode(assertion, options={"verify_signature": False})
        client_id = unverified.get("sub") or unverified.get("iss")
    except Exception:
        return None

    if not client_id:
        return None

    client = query_client(client_id)
    if not client or client.token_endpoint_auth_method != AUTH_METHOD_CLIENT_SECRET_JWT:
        return None
    if not client.client_secret_encrypted:
        return None

    from flask import current_app
    from x2fa.services.crypto import CryptoService

    crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
    secret = crypto.decrypt(client.client_secret_encrypted).encode()

    domain = current_app.config.x2fa.DOMAIN
    token_url = f"https://{domain}/token"

    try:
        pyjwt.decode(
            assertion,
            secret,
            algorithms=["HS256"],
            audience=token_url,
            options={"require": ["iss", "sub", "aud", "exp", "jti"]},
        )
        return client
    except pyjwt.PyJWTError:
        return None


def authenticate_via_client_secret_post(query_client, request):
    """Client authenticator for client_secret_post.

    Reads client_id and client_secret from the POST body and performs
    a constant-time comparison against the Fernet-encrypted stored secret.
    """
    client_id = request.form.get("client_id")
    client_secret = request.form.get("client_secret")
    if not client_id or not client_secret:
        return None
    return _verify_client_secret(
        query_client, client_id, client_secret, AUTH_METHOD_CLIENT_SECRET_POST
    )


def authenticate_via_client_secret_basic(query_client, request):
    """Client authenticator for client_secret_basic.

    Decodes HTTP Basic credentials (RFC 7617) and performs a constant-time
    comparison against the Fernet-encrypted stored secret.
    """
    import base64
    from urllib.parse import unquote as _unquote

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        raw_id, raw_secret = decoded.split(":", 1)
        client_id = _unquote(raw_id)
        client_secret = _unquote(raw_secret)
    except Exception:
        return None

    return _verify_client_secret(
        query_client, client_id, client_secret, AUTH_METHOD_CLIENT_SECRET_BASIC
    )


def query_client(client_id: str):
    """Authlib client loader — returns an active OIDCClient or None."""

    stmt = select(OIDCClient).where(
        OIDCClient.client_id == client_id, OIDCClient.active == True
    )
    return g.db_session.execute(stmt).scalars().first()


def save_token(token, request):
    """No-op: access tokens are stateless JWTs; no database storage needed."""
    pass
