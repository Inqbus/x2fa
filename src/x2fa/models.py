import secrets
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
from cryptography.exceptions import InvalidSignature
from cryptography.x509.oid import NameOID

from sqlalchemy.sql.schema import Column, Index
from sqlalchemy.sql.sqltypes import LargeBinary, String, Integer, Boolean, DateTime, Text

from x2fa.constants import NEVER_EXPIRES, NEVER_USED

from sqlalchemy.orm import declarative_base
Base = declarative_base()


class TrustedCA(Base):
    """A trusted Certificate Authority used to authenticate OIDC clients via mTLS."""

    __tablename__ = "trusted_ca"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(100), nullable=False, unique=True)
    cert_pem   = Column(Text, nullable=False)   # PEM-encoded root or intermediate CA cert
    active     = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)  # None = not tracked

    def verify_certificate(self, client_cert_pem: str) -> dict:
        """Validates client_cert_pem against this CA.

        Returns {'valid': True, 'client_id': <CN>} on success,
        or {'valid': False, 'reason': <str>} on failure.

        Checks:
        - PEM is a valid X.509 certificate
        - Certificate is within its validity period
        - Certificate is signed by this CA
        - CN attribute is present (used as client_id)
        """
        try:
            client_cert = x509.load_pem_x509_certificate(client_cert_pem.encode())
        except Exception as exc:
            return {"valid": False, "reason": f"Failed to parse client certificate: {exc}"}

        now = datetime.now(timezone.utc)
        not_before = client_cert.not_valid_before_utc
        not_after  = client_cert.not_valid_after_utc

        if now < not_before:
            return {"valid": False, "reason": "Certificate not yet valid"}
        if now > not_after:
            return {"valid": False, "reason": "Certificate has expired"}

        try:
            ca_cert = x509.load_pem_x509_certificate(self.cert_pem.encode())
        except Exception as exc:
            return {"valid": False, "reason": f"Failed to parse CA certificate: {exc}"}

        ca_public_key = ca_cert.public_key()
        try:
            key_type = type(ca_public_key).__name__
            if "RSA" in key_type:
                ca_public_key.verify(
                    client_cert.signature,
                    client_cert.tbs_certificate_bytes,
                    PKCS1v15(),
                    client_cert.signature_hash_algorithm,
                )
            elif "EC" in key_type:
                ca_public_key.verify(
                    client_cert.signature,
                    client_cert.tbs_certificate_bytes,
                    ECDSA(client_cert.signature_hash_algorithm),
                )
            else:
                return {"valid": False, "reason": f"Unsupported CA key type: {key_type}"}
        except InvalidSignature:
            return {"valid": False, "reason": "Certificate signature is invalid"}
        except Exception as exc:
            return {"valid": False, "reason": f"Signature verification failed: {exc}"}

        try:
            cn = client_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        except (IndexError, Exception):
            return {"valid": False, "reason": "Certificate has no CN attribute"}

        return {"valid": True, "client_id": cn}


class Credential(Base):
    __tablename__ = "credential"

    credential_id = Column(LargeBinary, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    authenticator_type = Column(String(20), nullable=False)  # platform / roaming
    device_type = Column(
        String(20), nullable=False, default="single_device"
    )  # single_device / multi_device
    # WebAuthn spec §5.8.4: transport hints are OPTIONAL. Platform authenticators
    # (Touch ID, Windows Hello, Android biometrics) communicate internally and have
    # no physical transport to report. Empty string = "not reported by authenticator".
    transport = Column(
        String(50), nullable=False, default=""
    )  # usb / nfc / ble / hybrid / internal / "" = unknown
    is_passkey = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_USED sentinel: set at registration; replaced on first successful assertion.
    last_used_at = Column(DateTime, nullable=False, default=NEVER_USED)

    __table_args__ = (Index("idx_cred_user_created", "user_id", "created_at"),)


class Challenge(Base):
    """Short-lived WebAuthn challenge (TTL 5 minutes, single-use)."""

    __tablename__ = "challenge"

    challenge_id = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    challenge = Column(LargeBinary, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, nullable=False, default=False)


class TOTPSecret(Base):
    __tablename__ = "totp_secret"

    user_id = Column(String(255), primary_key=True)
    secret_encrypted = Column(LargeBinary, nullable=False)
    verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    # NEVER_USED sentinel: set when the row is created (QR-code scanned, verified=False).
    # Replaced with the actual timestamp after the first successful code check.
    # The anti-replay check in totp_helpers.verify_code() always computes the delta;
    # NEVER_USED is far enough in the past that the 30-second window never triggers.
    last_used_at = Column(DateTime, nullable=False, default=NEVER_USED)


class BackupCode(Base):
    __tablename__ = "backup_code"

    code_hash = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    # NEVER_USED sentinel: set at creation; replaced with the redemption timestamp
    # when the code is consumed. Active codes: used_at == NEVER_USED.
    used_at = Column(DateTime, nullable=False, default=NEVER_USED)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255), nullable=False, index=True)
    action = Column(
        String(50), nullable=False, index=True
    )  # setup / verify / fail
    method = Column(
        String(50), nullable=False
    )  # webauthn_platform / webauthn_roaming / totp / backup
    ip_hash = Column(
        String(64), nullable=False
    )  # SHA256(ip + secret) — no plaintext stored
    timestamp = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


# ---------------------------------------------------------------------------
# New OIDC models
# ---------------------------------------------------------------------------


class OIDCClient(Base):
    """Registered OIDC client (relying party)."""

    __tablename__ = "oidc_client"

    client_id = Column(String(255), primary_key=True)
    client_secret = Column(String(255), nullable=False)
    redirect_uris = Column(Text, nullable=False)  # newline-separated
    allowed_scopes = Column(
        String(255), nullable=False, default="openid app:setup"
    )  # space-separated
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
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
        now_utc = datetime.now(timezone.utc)
        print(f'exp: {exp}, now_utc: {now_utc}')
        return now_utc > exp

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
