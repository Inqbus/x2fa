from datetime import datetime, timezone

from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.sqltypes import LargeBinary, String, Integer, Boolean, DateTime, Text

from x2fa.constants import NEVER_EXPIRES, AUTH_METHOD_TLS_CLIENT_AUTH
from x2fa.model.base import Base


class OIDCClient(Base):
    """Registered OIDC client (relying party)."""

    __tablename__ = "oidc_client"

    client_id = Column(String(255), primary_key=True)
    redirect_uris = Column(Text, nullable=False)  # newline-separated
    allowed_scopes = Column(
        String(255), nullable=False, default="openid app:setup"
    )  # space-separated
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    token_endpoint_auth_method = Column(
        String(50), nullable=False, default=AUTH_METHOD_TLS_CLIENT_AUTH
    )
    jwks_uri = Column(String(255), nullable=True)            # private_key_jwt
    client_cert_fingerprint = Column(String(95), nullable=True)  # self_signed_tls: SHA-256 hex
    client_secret_encrypted = Column(LargeBinary, nullable=True) # client_secret_*: Fernet-encrypted

    # --- Authlib interface ---

    def get_client_id(self):
        return self.client_id

    def get_default_redirect_uri(self):
        uris = [u.strip() for u in self.redirect_uris.splitlines() if u.strip()]
        return uris[0] if uris else None

    def check_redirect_uri(self, redirect_uri: str) -> bool:
        uris = [u.strip() for u in self.redirect_uris.splitlines() if u.strip()]
        return redirect_uri in uris

    def check_grant_type(self, grant_type: str) -> bool:
        return grant_type == "authorization_code"

    def check_response_type(self, response_type: str) -> bool:
        return response_type == "code"

    def get_allowed_scope(self, scope: str) -> str:
        """Returns the allowed subset of the requested scope."""
        allowed = set(self.allowed_scopes.split())
        requested = set(scope.split())
        return " ".join(allowed & requested)

    def check_token_endpoint_auth_method(self, method: str) -> bool:
        return method == self.token_endpoint_auth_method

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:
        if endpoint == "token":
            return self.check_token_endpoint_auth_method(method)
        return True


class AuthorizationCode(Base):
    """OIDC authorization code — PKCE S256, single-use, 60-second TTL."""

    __tablename__ = "authorization_code"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(255), nullable=False, unique=True, index=True)
    client_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    redirect_uri = Column(Text, nullable=False)
    scope = Column(String(255), nullable=False)
    # nullable: OIDC Core §3.1.2.1 declares nonce OPTIONAL in the code flow.
    # None here is not "forgotten state" — it means the RP did not send a nonce.
    # Authlib's get_nonce() must return None (not "") to suppress the nonce claim
    # in the ID token; _authorize_continue_url() filters None values from the URL.
    # A sentinel string would break both of these invariants.
    nonce = Column(String(255), nullable=True)
    # /authorize enforces PKCE S256 as mandatory (aborts if code_challenge is absent).
    # These columns are therefore always set when a code is issued.
    code_challenge = Column(String(255), nullable=False)
    code_challenge_method = Column(String(10), nullable=False)
    auth_time = Column(Integer, nullable=False)  # Unix timestamp
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, nullable=False, default=False)

    def is_expired(self) -> bool:
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp

    # --- Authlib interface ---

    def get_redirect_uri(self) -> str:
        return self.redirect_uri

    def get_scope(self) -> str:
        return self.scope

    def get_nonce(self):
        return self.nonce

    def get_auth_time(self) -> int:
        return self.auth_time

    def get_acr(self):
        return None

    def get_amr(self):
        return None


class SigningKey(Base):
    """EC key pair for ID token signing (ES256). Private key is Fernet-encrypted."""

    __tablename__ = "signing_key"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kid = Column(String(255), nullable=False, unique=True)
    private_key_encrypted = Column(LargeBinary, nullable=False)
    public_key_pem = Column(Text, nullable=False)
    algorithm = Column(String(10), nullable=False, default="ES256")
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_EXPIRES sentinel: set at key creation for keys with no planned expiry.
    # Because NEVER_EXPIRES > any real datetime, the query "expires_at > now" works
    # uniformly for both expiring and non-expiring keys — no special-casing needed.
    expires_at = Column(DateTime, nullable=False, default=NEVER_EXPIRES)

    def get_private_key(self, fernet):
        """Decrypts and returns the EC private key object."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        pem = fernet.decrypt(self.private_key_encrypted)
        return load_pem_private_key(pem, password=None)
