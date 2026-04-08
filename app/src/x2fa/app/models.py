import secrets
from datetime import datetime, timezone

from app.src.x2fa.app.constants import NEVER_EXPIRES, NEVER_USED
from app.src.x2fa.app.extensions import db


# ---------------------------------------------------------------------------
# Legacy 2FA models (ported from raw SQLAlchemy to Flask-SQLAlchemy)
# ---------------------------------------------------------------------------


class Credential(db.Model):
    __tablename__ = "credentials"

    credential_id = db.Column(db.LargeBinary, primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.Integer, nullable=False, default=0)
    authenticator_type = db.Column(db.String(20), nullable=False)  # platform / roaming
    device_type = db.Column(
        db.String(20), nullable=False, default="single_device"
    )  # single_device / multi_device
    # WebAuthn spec §5.8.4: transport hints are OPTIONAL. Platform authenticators
    # (Touch ID, Windows Hello, Android biometrics) communicate internally and have
    # no physical transport to report. Empty string = "not reported by authenticator".
    transport = db.Column(
        db.String(50), nullable=False, default=""
    )  # usb / nfc / ble / hybrid / internal / "" = unknown
    is_passkey = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_USED sentinel: set at registration; replaced on first successful assertion.
    last_used_at = db.Column(db.DateTime, nullable=False, default=NEVER_USED)

    __table_args__ = (db.Index("idx_cred_user_created", "user_id", "created_at"),)


class Challenge(db.Model):
    """Short-lived WebAuthn challenge (TTL 5 minutes, single-use)."""

    __tablename__ = "challenges"

    challenge_id = db.Column(db.String(255), primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    challenge = db.Column(db.LargeBinary, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used = db.Column(db.Boolean, nullable=False, default=False)


class TOTPSecret(db.Model):
    __tablename__ = "totp_secrets"

    user_id = db.Column(db.String(255), primary_key=True)
    secret_encrypted = db.Column(db.LargeBinary, nullable=False)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_USED sentinel: set when the row is created (QR-code scanned, verified=False).
    # Replaced with the actual timestamp after the first successful code check.
    # The anti-replay check in totp_helpers.verify_code() always computes the delta;
    # NEVER_USED is far enough in the past that the 30-second window never triggers.
    last_used_at = db.Column(db.DateTime, nullable=False, default=NEVER_USED)


class BackupCode(db.Model):
    __tablename__ = "backup_codes"

    code_hash = db.Column(db.String(255), primary_key=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    # NEVER_USED sentinel: set at creation; replaced with the redemption timestamp
    # when the code is consumed. Active codes: used_at == NEVER_USED.
    used_at = db.Column(db.DateTime, nullable=False, default=NEVER_USED)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(255), nullable=False, index=True)
    action = db.Column(
        db.String(50), nullable=False, index=True
    )  # setup / verify / fail
    method = db.Column(
        db.String(50), nullable=False
    )  # webauthn_platform / webauthn_roaming / totp / backup
    ip_hash = db.Column(
        db.String(64), nullable=False
    )  # SHA256(ip + secret) — no plaintext stored
    timestamp = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


# ---------------------------------------------------------------------------
# New OIDC models
# ---------------------------------------------------------------------------


class OIDCClient(db.Model):
    """Registered OIDC client (relying party)."""

    __tablename__ = "oidc_clients"

    client_id = db.Column(db.String(255), primary_key=True)
    client_secret = db.Column(db.String(255), nullable=False)
    redirect_uris = db.Column(db.Text, nullable=False)  # newline-separated
    allowed_scopes = db.Column(
        db.String(255), nullable=False, default="openid app:setup"
    )  # space-separated
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # --- Authlib interface ---

    def get_client_id(self):
        return self.client_id

    def get_default_redirect_uri(self):
        uris = [u.strip() for u in self.redirect_uris.splitlines() if u.strip()]
        return uris[0] if uris else None

    def check_redirect_uri(self, redirect_uri: str) -> bool:
        uris = [u.strip() for u in self.redirect_uris.splitlines() if u.strip()]
        return redirect_uri in uris

    def has_client_secret(self) -> bool:
        return bool(self.client_secret)

    def check_client_secret(self, client_secret: str) -> bool:
        return secrets.compare_digest(self.client_secret, client_secret)

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
        return method in ("client_secret_post", "client_secret_basic")

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:
        if endpoint == "token":
            return self.check_token_endpoint_auth_method(method)
        return True


class AuthorizationCode(db.Model):
    """OIDC authorization code — PKCE S256, single-use, 60-second TTL."""

    __tablename__ = "authorization_codes"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code = db.Column(db.String(255), nullable=False, unique=True, index=True)
    client_id = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.String(255), nullable=False)
    redirect_uri = db.Column(db.Text, nullable=False)
    scope = db.Column(db.String(255), nullable=False)
    # nullable: OIDC Core §3.1.2.1 declares nonce OPTIONAL in the code flow.
    # None here is not "forgotten state" — it means the RP did not send a nonce.
    # Authlib's get_nonce() must return None (not "") to suppress the nonce claim
    # in the ID token; _authorize_continue_url() filters None values from the URL.
    # A sentinel string would break both of these invariants.
    nonce = db.Column(db.String(255), nullable=True)
    # /authorize enforces PKCE S256 as mandatory (aborts if code_challenge is absent).
    # These columns are therefore always set when a code is issued.
    code_challenge = db.Column(db.String(255), nullable=False)
    code_challenge_method = db.Column(db.String(10), nullable=False)
    auth_time = db.Column(db.Integer, nullable=False)  # Unix timestamp
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used = db.Column(db.Boolean, nullable=False, default=False)

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


class SigningKey(db.Model):
    """EC key pair for ID token signing (ES256). Private key is Fernet-encrypted."""

    __tablename__ = "signing_keys"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    kid = db.Column(db.String(255), nullable=False, unique=True)
    private_key_encrypted = db.Column(db.LargeBinary, nullable=False)
    public_key_pem = db.Column(db.Text, nullable=False)
    algorithm = db.Column(db.String(10), nullable=False, default="ES256")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_EXPIRES sentinel: set at key creation for keys with no planned expiry.
    # Because NEVER_EXPIRES > any real datetime, the query "expires_at > now" works
    # uniformly for both expiring and non-expiring keys — no special-casing needed.
    expires_at = db.Column(db.DateTime, nullable=False, default=NEVER_EXPIRES)

    def get_private_key(self, fernet):
        """Decrypts and returns the EC private key object."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        pem = fernet.decrypt(self.private_key_encrypted)
        return load_pem_private_key(pem, password=None)
