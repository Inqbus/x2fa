import secrets
from datetime import datetime, timezone, timedelta

from app.extensions import db


# ---------------------------------------------------------------------------
# Bestehende 2FA-Modelle (auf Flask-SQLAlchemy portiert)
# ---------------------------------------------------------------------------

class Credential(db.Model):
    __tablename__ = "credentials"

    credential_id    = db.Column(db.LargeBinary, primary_key=True)
    user_id          = db.Column(db.String(255), nullable=False, index=True)
    public_key       = db.Column(db.LargeBinary, nullable=False)
    sign_count       = db.Column(db.Integer, nullable=False, default=0)
    authenticator_type = db.Column(db.String(20), nullable=False)
    device_type      = db.Column(db.String(20), nullable=False, default="single_device")
    transport        = db.Column(db.String(50), nullable=True)
    is_passkey       = db.Column(db.Boolean, nullable=False, default=False)
    created_at       = db.Column(db.DateTime, nullable=False,
                                 default=lambda: datetime.now(timezone.utc))
    last_used_at     = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.Index("idx_cred_user_created", "user_id", "created_at"),
    )


class Challenge(db.Model):
    __tablename__ = "challenges"

    challenge_id = db.Column(db.String(255), primary_key=True)
    user_id      = db.Column(db.String(255), nullable=False, index=True)
    challenge    = db.Column(db.LargeBinary, nullable=False)
    expires_at   = db.Column(db.DateTime, nullable=False, index=True)
    used         = db.Column(db.Boolean, nullable=False, default=False)


class TOTPSecret(db.Model):
    __tablename__ = "totp_secrets"

    user_id          = db.Column(db.String(255), primary_key=True)
    secret_encrypted = db.Column(db.LargeBinary, nullable=False)
    verified         = db.Column(db.Boolean, nullable=False, default=False)
    created_at       = db.Column(db.DateTime, nullable=False,
                                 default=lambda: datetime.now(timezone.utc))
    last_used_at     = db.Column(db.DateTime, nullable=True)


class BackupCode(db.Model):
    __tablename__ = "backup_codes"

    code_hash  = db.Column(db.String(255), primary_key=True)
    user_id    = db.Column(db.String(255), nullable=False, index=True)
    used_at    = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id        = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id   = db.Column(db.String(255), nullable=False, index=True)
    action    = db.Column(db.String(50), nullable=False, index=True)
    method    = db.Column(db.String(50), nullable=False)
    ip_hash   = db.Column(db.String(64), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False,
                          default=lambda: datetime.now(timezone.utc), index=True)


# ---------------------------------------------------------------------------
# Neue OIDC-Modelle
# ---------------------------------------------------------------------------

class OIDCClient(db.Model):
    """Registrierter OIDC-Client (Relying Party)."""
    __tablename__ = "oidc_clients"

    client_id      = db.Column(db.String(255), primary_key=True)
    client_secret  = db.Column(db.String(255), nullable=False)
    # Redirect-URIs: zeilengetrennt
    redirect_uris  = db.Column(db.Text, nullable=False)
    # Erlaubte Scopes: leerzeichen-getrennt, z.B. "openid x2fa:setup"
    allowed_scopes = db.Column(db.String(255), nullable=False,
                               default="openid x2fa:setup")
    active         = db.Column(db.Boolean, nullable=False, default=True)
    created_at     = db.Column(db.DateTime, nullable=False,
                               default=lambda: datetime.now(timezone.utc))

    # --- Authlib-Interface ---

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
        """Gibt den erlaubten Teil des angeforderten Scopes zurück."""
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
    """OIDC Authorization Code (PKCE S256, einmalig verwendbar)."""
    __tablename__ = "authorization_codes"

    id                   = db.Column(db.Integer, primary_key=True, autoincrement=True)
    code                 = db.Column(db.String(255), nullable=False, unique=True, index=True)
    client_id            = db.Column(db.String(255), nullable=False)
    user_id              = db.Column(db.String(255), nullable=False)
    redirect_uri         = db.Column(db.Text, nullable=False)
    scope                = db.Column(db.String(255), nullable=False)
    nonce                = db.Column(db.String(255), nullable=True)
    code_challenge       = db.Column(db.String(255), nullable=True)
    code_challenge_method = db.Column(db.String(10), nullable=True)
    auth_time            = db.Column(db.Integer, nullable=False)  # Unix-Timestamp
    expires_at           = db.Column(db.DateTime, nullable=False, index=True)
    used                 = db.Column(db.Boolean, nullable=False, default=False)

    def is_expired(self) -> bool:
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp

    # --- Authlib-Interface ---

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
    """EC-Schlüsselpaar für ID-Token-Signierung (ES256)."""
    __tablename__ = "signing_keys"

    id                    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    kid                   = db.Column(db.String(255), nullable=False, unique=True)
    private_key_encrypted = db.Column(db.LargeBinary, nullable=False)
    public_key_pem        = db.Column(db.Text, nullable=False)
    algorithm             = db.Column(db.String(10), nullable=False, default="ES256")
    active                = db.Column(db.Boolean, nullable=False, default=True)
    created_at            = db.Column(db.DateTime, nullable=False,
                                      default=lambda: datetime.now(timezone.utc))
    expires_at            = db.Column(db.DateTime, nullable=True)

    def get_private_key(self, fernet):
        """Entschlüsselt und gibt den privaten EC-Schlüssel zurück."""
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        pem = fernet.decrypt(self.private_key_encrypted)
        return load_pem_private_key(pem, password=None)
