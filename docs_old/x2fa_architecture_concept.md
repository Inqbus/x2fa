# X2FA Architecture v2.1
**FIDO2 Microservice with OIDC Provider – Self-Sovereign Key Architecture**
*Date: 2026-04-22*

> **ARCHIVED DOCUMENT** - Some sections describe the old Dynaconf-based configuration.
> The current system uses plain TOML files via `tomllib`.

---

## 1. Vision & Value Proposition

X2FA is a standalone 2FA microservice with a full OIDC provider (OpenID Connect), integrated into existing applications via the standardized Authorization Code Flow. Supports all FIDO2 authenticator classes (Platform, Roaming, Hybrid) as well as TOTP fallback for universal platform compatibility (including Linux).

**Value Proposition:** FIDO2 authentication without framework overhead, database-agnostic, with an intelligent fallback strategy for all platforms (macOS, Windows, Linux, iOS, Android). Communication via the OIDC standard — no proprietary JWTs, **no shared secrets between app and X2FA** (Self-Sovereign Keys via X.509/mTLS).

### Bring Your Own Domain + Bring Your Own Infrastructure

| Component | User provides | X2FA provides |
|-----------|--------------|---------------|
| **Domain** | DNS A record (`2fa.example.com` → server IP) | Automatic RP-ID configuration |
| **TLS/Infrastructure** | Caddy/nginx/Traefik/Cloudflare | HTTP backend on localhost:5000 |
| **Database** | SQLite (default), PostgreSQL or MySQL | SQLAlchemy ORM with migrations |
| **Authenticator** | FaceID/TouchID (Apple), Hello (Windows), Android biometrics, YubiKey (USB/NFC), Phone-as-Key (Hybrid) | Auto-detection of available methods, cross-platform support |
| **Fallback** | TOTP app (Google Authenticator etc.) | Encrypted storage (Fernet) |
| **Emergency** | 10 backup codes | Single-use validation |
| **Integration** | OIDC client (X.509 certificate or private key) | OIDC Authorization Code Flow, JWKS endpoint, Discovery, mTLS |

### Authenticator Strategy (Cross-Platform)

| Platform | Primary method | Fallback | Implementation |
|----------|---------------|----------|----------------|
| **macOS/iOS** | Secure Enclave (TouchID/FaceID) | TOTP | `navigator.credentials` without attachment filter |
| **Windows 10/11** | TPM 2.0 (Windows Hello) | TOTP | Platform detection |
| **Android** | StrongBox/TEE | TOTP | Biometrics API |
| **Linux Desktop** | Hybrid/Phone-as-Key or YubiKey | TOTP | QR code for phone auth or USB roaming |
| **Server/Headless** | TOTP or backup codes | – | No WebAuthn available |

No `authenticatorAttachment: "platform"` restriction — enables YubiKey and hybrid transport.

---

## 2. System Architecture

### Component Diagram

```mermaid
graph TB
    subgraph "TRUST ROOT"
        CA["Internal CA<br/>Root Certificate<br/>Trust Anchor for X2FA"]
    end
    
    subgraph "CLIENT"
        Browser["Browser<br/>Vanilla JS inline"]
        PlatformAuth["Platform Authenticator<br/>FaceID / TouchID / Windows Hello"]
        RoamingAuth["Roaming Authenticator<br/>YubiKey USB/NFC"]
        HybridAuth["Hybrid/Phone<br/>Android/iPhone via QR/BLE"]
        TOTPApp["TOTP app<br/>Google Authenticator etc."]
        
        subgraph "Main application"
            App["Flask/Django/Node.js<br/>OIDC Client"]
            Key["Private key<br/>(local, AES-encrypted)"]
            Cert["X.509 certificate<br/>CN=client_id"]
        end
    end

    subgraph "INFRASTRUCTURE"
        TLS["HTTPS termination<br/>Caddy / nginx / Traefik"]
    end

    subgraph "X2FA SERVICE"
        Flask["Flask 3.1+<br/>HTTP localhost:5000"]
        
        subgraph "AUTHENTICATOR"
            MTLS["mTLS validation<br/>or private_key_jwt"]
            TrustedCA["Trusted CA store<br/>(root certs)"]
        end

        subgraph "DATABASE LAYER"
            SQLAlchemy["SQLAlchemy 2.0+ ORM"]
        end

        subgraph "DATABASE"
            SQLite[("SQLite Default")]
            Postgres[("PostgreSQL")]
            MySQL[("MySQL")]
        end
    end

    MainApp["MAIN APPLICATION"]

    Browser <-->|"HTTPS TLS 1.3"| TLS
    TLS <-->|"HTTP"| Flask
    Flask <-->|"SQL"| SQLAlchemy
    SQLAlchemy <-->|"Engine"| SQLite
    SQLAlchemy <-->|"Engine"| Postgres
    SQLAlchemy <-->|"Engine"| MySQL

    Browser <-->|"WebAuthn API"| PlatformAuth
    Browser <-->|"WebAuthn API"| RoamingAuth
    Browser <-->|"caBLE/QR"| HybridAuth
    Browser -.->|"Manual entry"| TOTPApp

    App <-->|"mTLS or JWT"| TLS
    TLS <-->|"X-Client-Certificate"| Flask
    
    App <-->|"OIDC Authorization Code Flow"| TLS
    
    Flask -->|"verifies"| TrustedCA
    TrustedCA -.->|"signed by"| Cert
    CA -.->|"Root cert"| TrustedCA
    
    style PlatformAuth fill:#f9f
    style RoamingAuth fill:#f9f
    style HybridAuth fill:#f9f
    style Flask fill:#ff9
    style SQLAlchemy fill:#bbf
    style SQLite fill:#fbb
    style TrustedCA fill:#bfb
```

### HTTPS Strategies (Resolver-agnostic)

| Setup | Use case | Configuration |
|-------|----------|---------------|
| **Caddy** | Zero-config, auto-HTTPS | `reverse_proxy localhost:5000`, automatic certificates, `tls internal` for internal CA |
| **nginx** | Enterprise, manual control | `proxy_pass http://127.0.0.1:5000`, `ssl_verify_client optional_no_ca` for mTLS |
| **Traefik** | Docker/cloud-native | Label-based discovery, auto-HTTPS, `tls.options.mtls.clientAuth` |

### Database Strategies

| Setup | Connection string | Use case |
|-------|-------------------|----------|
| **SQLite** | `sqlite:///var/lib/x2fa/db.sqlite` | Default, zero-config, single-node |
| **PostgreSQL** | `postgresql://user:pass@host/x2fa` | Enterprise, HA setups |
| **MySQL** | `mysql+pymysql://user:pass@host/x2fa` | Existing infrastructure |

---

## 3. Technology Stack

| Layer | Technology | Version |
|-------|------------|---------|
| **Framework** | Flask | 3.1.3+ |
| **Python** | CPython | 3.11+ |
| **ORM** | SQLAlchemy | 2.0+, `pool_pre_ping=True` |
| **Schema** | `flask init-db` (`create_all`) | No Alembic migrations; run once on first install (**destructive**: drops + recreates all tables). In test mode schema is created automatically on startup. |
| **WebAuthn** | py_webauthn | 2.7.1+ |
| **TOTP** | pyotp | 2.9+, RFC 6238, ±30 s window |
| **QR code** | qrcode + Pillow | 8.2+ / 12.2+ |
| **OIDC** | Authlib | 1.6.9+, Authorization Code Flow + PKCE, JWKS, Discovery |
| **Crypto** | cryptography | 46.0.7+, Fernet (AES-128-CBC + HMAC-SHA256), X.509 |
| **Hashing** | bcrypt | 5.0.0+, rounds=12 |
| **Rate limiting** | Flask-Limiter | 4.1.1+, moving-window |
| **Configuration** | Dynaconf | 3.2.13+, TOML files, environments |
| **i18n** | flask-babelplus | 2.2.0+, 16 languages |
| **WSGI** | Gunicorn | 25.3.0+ |
| **Frontend** | Vanilla JS | ~50 lines inline, CSP-nonced, no build tools |

### Dependencies (`pyproject.toml`)

```
flask>=3.1.3
flask-sqlalchemy>=3.1.1
flask-limiter>=4.1.1
secure>=1.0.1
authlib>=1.6.9
gunicorn>=25.3.0
webauthn>=2.7.1
pyotp>=2.9.0
qrcode>=8.2
Pillow>=12.2.0
cryptography>=46.0.7
bcrypt>=5.0.0
redis>=7.4.0
dynaconf>=3.2.13
flask-babelplus>=2.2.0

# Optional:
psycopg2-binary>=2.9.0  # PostgreSQL
pymysql>=1.1.0           # MySQL
```

---

## 4. Configuration

### Dynaconf with TOML Files

Configuration is managed by Dynaconf using five thematically separated TOML files in `src/x2fa/config_files/`. Each file supports the environments `[default]`, `[production]`, `[testing]`, `[e2e]`. Environment variables with the respective prefix override TOML values.

| Config file | Dynaconf namespace | Env prefix | Content |
|---|---|---|---|
| `x2fa_config.toml` | `app.config.x2fa` | `X2FA_` | Host, port, domain, testing flag |
| `db_config.toml` | `app.config.x2fa_database` | `X2FA_DB_` | `SQLALCHEMY_DATABASE_URI` |
| `security_config.toml` | `app.config.x2fa_security` | `X2FA_SECURITY_` | `SECRET_KEY`, `SECRET_SALT`, session cookie settings |
| `ratelimit_config.toml` | `app.config.x2fa_ratelimit` | `X2FA_RATELIMIT_` | Rate limit values, Redis URI, strategy |
| `babel_config.toml` | `app.config.x2fa_babel` | `X2FA_BABEL_` | Language settings |

### App Factory with Startup Checks

```python
# src/x2fa/init_app/config.py
import tomllib
from x2fa.helpers.attr_dict import AttrDict

def configure(app: Flask):
    config_by_namespace = load_config()
    for namespace, config_file_name in CONFIGS.items():
        setattr(app.config, namespace, getattr(config_by_namespace, namespace))

def load_config():
    config_dir_path = config_dir()
    _pool = ConfigPool(config_dir_path)
    
    for namespace, config_file_name in CONFIGS.items():
        config_file_path = config_dir_path / config_file_name
        if not config_file_path.exists():
            raise RuntimeError(...)
        
        with open(config_file_path, "rb") as config_file:
            data = tomllib.load(config_file)
        
        # Use [production] section if available, otherwise [default]
        if "production" in data:
            section_data = data["production"]
        elif "default" in data:
            section_data = data["default"]
        else:
            section_data = {}
        
        simple_namespace = AttrDict(**section_data)
        _pool.add_config(namespace, simple_namespace)
    
    return _pool
```

### Session Security (`security_config.toml`)

```toml
[default]
SESSION_COOKIE_SECURE   = true   # HTTPS only
SESSION_COOKIE_HTTPONLY = true   # no JS access
SESSION_COOKIE_SAMESITE = "Lax"  # CSRF protection
PERMANENT_SESSION_LIFETIME = 600 # 10 minutes in seconds

[testing]
SESSION_COOKIE_SECURE   = false
SESSION_COOKIE_SAMESITE = false
```

---

## 5. Authlib Integration (Self-Sovereign Keys)

### Session Pattern: Two Contexts, Two APIs

The codebase intentionally uses two different session APIs — each correct for its context:

| Context | API | Why |
|---------|-----|-----|
| **Web routes / grant methods** | `g.db_session` | Flask opens a session in `before_request` and commits/closes it in `teardown_appcontext`. All request-scoped code must use this shared session. |
| **CLI commands** | `with db.session_scope() as db_session:` | No Flask request context exists; `session_scope()` creates an explicit session with auto-commit/rollback. |

Using `session_scope()` inside a request handler would open a second, independent transaction and bypass the request-scoped lifecycle. Using `g.db_session` in a CLI command would raise `RuntimeError` (no request context).

### Grant Class

```python
# src/x2fa/oidc/grants.py
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core.grants import OpenIDCode
from sqlalchemy import select
from flask import g


class S256OnlyCodeChallenge(CodeChallenge):
    """Restricts PKCE to S256 only — 'plain' is explicitly rejected."""
    SUPPORTED_CODE_CHALLENGE_METHOD = ["S256"]


class X2FAAuthorizationCodeGrant(AuthorizationCodeGrant):
    """
    PKCE S256 enforced, plain explicitly rejected.
    OpenIDCode functionality is added as an extension via register_grant().
    Supports Self-Sovereign Keys: tls_client_auth and private_key_jwt.
    """
    TOKEN_ENDPOINT_AUTH_METHODS = [
        AUTH_METHOD_TLS_CLIENT_AUTH,  # X.509 client certificate via mTLS
        AUTH_METHOD_PRIVATE_KEY_JWT,  # JWT with x5c header (certificate chain)
    ]

    def save_authorization_code(self, code, request):
        user_id = request.user  # set by create_authorization_response(grant_user=...)
        payload = request.payload
        auth_code = AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            user_id=user_id,
            redirect_uri=(payload.redirect_uri or request.client.get_default_redirect_uri()),
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
        stmt = select(AuthorizationCode).where(
            AuthorizationCode.code == code,
            AuthorizationCode.client_id == client.client_id,
        )
        auth_code = g.db_session.execute(stmt).scalars().first()
        if not auth_code or auth_code.is_expired() or auth_code.used:
            return None
        return auth_code

    def delete_authorization_code(self, authorization_code):
        """Marks code as used (not physically deleted — preserves nonce for replay protection)."""
        authorization_code.used = True
        g.db_session.commit()

    def authenticate_user(self, authorization_code):
        return authorization_code.user_id


class X2FAOpenIDCode(OpenIDCode):
    """
    OpenIDCode extension: generates ES256-signed ID tokens and enforces nonce replay protection.
    Registered as an extension on X2FAAuthorizationCodeGrant via register_grant().
    """

    def exists_nonce(self, nonce, request):
        """Replay protection: checks whether nonce was already used."""
        if not nonce:
            return False
        stmt = select(AuthorizationCode).where(AuthorizationCode.nonce == nonce)
        return g.db_session.execute(stmt).scalars().first() is not None

    def get_jwt_config(self, grant, client=None):
        """ID-Token signing configuration (ES256)."""
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        stmt = (
            select(SigningKey)
            .where(SigningKey.active == True)
            .where(SigningKey.expires_at > datetime.now(timezone.utc))
            .order_by(SigningKey.created_at.desc())
        )
        signing_key = g.db_session.execute(stmt).scalars().first()
        if not signing_key:
            raise RuntimeError("No active signing key! Run 'flask init-keys' first.")
        private_key = signing_key.get_private_key(crypto.get_fernet())
        return {
            "key": private_key,
            "alg": signing_key.algorithm,
            "iss": f"https://{current_app.config.x2fa.DOMAIN}",
            "exp": 60,
            "kid": signing_key.kid,
        }

    def generate_user_info(self, user, scope):
        return {"sub": user}

# Registration lives in src/x2fa/init_app/security.py (not at module level here):
#
#   oauth.init_app(app, query_client=query_client, save_token=save_token)
#   oauth.register_grant(
#       X2FAAuthorizationCodeGrant,
#       [S256OnlyCodeChallenge(required=True), X2FAOpenIDCode(require_nonce=False)],
#   )
#   token_url = f"https://{app.config.x2fa.DOMAIN}/token"
#   oauth.register_client_auth_method(AUTH_METHOD_TLS_CLIENT_AUTH, authenticate_via_mtls)
#   oauth.register_client_auth_method(AUTH_METHOD_PRIVATE_KEY_JWT, X2FAPrivateKeyJwtAuth(token_url))
```

---

## 6. Rate Limiting

### Configuration (`ratelimit_config.toml`)

```toml
[default]
RATELIMIT_STORAGE_URI   = "memory://"     # set to Redis URI in production
RATELIMIT_STRATEGY      = "moving-window" # protection against burst attacks at window boundaries
RATELIMIT_HEADERS_ENABLED = true

RATE_LIMIT_AUTHORIZE      = "10 per minute; 100 per hour"
RATE_LIMIT_TOKEN          = "20 per minute"
RATE_LIMIT_SETUP_COMPLETE = "5 per minute"
RATE_LIMIT_TOTP_SETUP     = "5 per minute; 20 per hour"
RATE_LIMIT_TOTP_VERIFY    = "5 per minute; 20 per hour"
RATE_LIMIT_WEBAUTHN_VERIFY = "10 per minute; 30 per hour"
RATE_LIMIT_BACKUP_VERIFY  = "3 per minute; 10 per hour"

CHALLENGE_TTL_MINUTES = 5
```

### Rationale for Limits

| Endpoint | Limit | Rationale |
|----------|-------|-----------|
| `/authorize` | 10/min, 100/h | OIDC entry point, moderate |
| `/token` | 20/min | Server-to-server, certificate validation |
| `POST /totp/verify` | 5/min, 20/h | 10⁶ possible codes → strict limit needed |
| `POST /backup/verify` | 3/min, 10/h | 8 hex characters = 4 billion combinations → very strict |
| WebAuthn verify | 10/min, 30/h | Replay-resistant via signatures, limit protects DB |

In production, `RATELIMIT_STORAGE_URI` must point to a Redis server (distributed rate limiting with multiple workers).

---

## 7. Cleanup Policy (Preserving Nonce Protection)

```python
# src/x2fa/cli.py — flask cleanup-codes
@click.command("cleanup-codes")
@with_appcontext
def cleanup_codes():
    """
    Deletes authorization codes older than 1 hour.
    Codes younger than 1 hour are retained for nonce replay protection:
    the nonce must remain queryable until all ID tokens issued from it expire.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    with db.session_scope() as db_session:
        stmt = select(AuthorizationCode).where(AuthorizationCode.expires_at < cutoff)
        old = db_session.execute(stmt).scalars().all()
    count = len(old)
    with db.session_scope() as db_session:
        for code in old:
            db_session.delete(code)
    click.echo(f"Deleted: {count} authorization codes (older than 1 hour).")
```

**Not allowed** (would break nonce protection):
```python
# WRONG: deletes codes immediately after use or after TTL expiry
select(AuthorizationCode).where(AuthorizationCode.used == True)
select(AuthorizationCode).where(AuthorizationCode.expires_at < now)
```

---

## 8. Database Schema (SQLAlchemy Models)

### Model `TrustedCA`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `Integer`, PK, autoincrement | |
| `name` | `String(100)`, unique | CA name (e.g. "inqbus-internal-ca") |
| `cert_pem` | `Text` | CA public key (root or intermediate) |
| `active` | `Boolean`, default=True | Active for validation |
| `created_at` | `DateTime` | Creation timestamp |
| `expires_at` | `DateTime`, nullable | CA expiry date |

Methods:
- `verify_certificate(client_cert_pem)`: Checks signature, validity period, and extracts CN as client_id.

### Model `OIDCClient` (Certificate-based)

| Field | Type | Description |
|-------|------|-------------|
| `client_id` | `String(255)`, PK | CN from the X.509 certificate |
| `token_endpoint_auth_method` | `String(50)` | `tls_client_auth` (default) or `private_key_jwt` |
| `redirect_uris` | `Text` | Newline-separated URIs; exact string match |
| `allowed_scopes` | `String(255)` | Default: `"openid app:setup"` |
| `jwks_uri` | `String(255)`, nullable | For private_key_jwt: client JWKS URL |
| `active` | `Boolean`, default=True | Revocation |
| `created_at` | `DateTime` | |

### Model `Credential` (FIDO2)

| Field | Type | Description |
|-------|------|-------------|
| `credential_id` | `LargeBinary`, PK | Base64URL-decoded FIDO2 credential ID |
| `user_id` | `String(255)`, Index | |
| `public_key` | `LargeBinary` | COSE key |
| `sign_count` | `Integer`, default=0 | Replay protection |
| `authenticator_type` | `String(20)` | `'platform'` / `'roaming'` |
| `device_type` | `String(20)` | `'single_device'` / `'multi_device'` |
| `transport` | `String(50)`, default=`""` | `usb` / `nfc` / `ble` / `hybrid` / `internal` |
| `is_passkey` | `Boolean`, default=False | Cloud-synced? |
| `created_at` | `DateTime` | UTC |
| `last_used_at` | `DateTime` | `NEVER_USED` sentinel at registration |

Index: `idx_cred_user_created` on `(user_id, created_at)`.

### Model `Challenge` (Temporary, 5 min TTL)

| Field | Type | Description |
|-------|------|-------------|
| `challenge_id` | `String(255)`, PK | UUID |
| `user_id` | `String(255)`, Index | |
| `challenge` | `LargeBinary` | 32–64 bytes |
| `expires_at` | `DateTime`, Index | Auto-cleanup |
| `used` | `Boolean`, default=False | Single-use |

### Model `TOTPSecret` (Fernet-encrypted)

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | `String(255)`, PK | |
| `secret_encrypted` | `LargeBinary` | Fernet(AES-128-CBC + HMAC) |
| `verified` | `Boolean`, default=False | Setup completed? |
| `created_at` | `DateTime` | |
| `last_used_at` | `DateTime` | `NEVER_USED` sentinel; replay protection (30 s window) |

### Model `BackupCode` (10 per user, single-use)

| Field | Type | Description |
|-------|------|-------------|
| `code_hash` | `String(255)`, PK | bcrypt hash of the user-facing 8-char hex code (rounds=12); plaintext never stored |
| `user_id` | `String(255)`, Index | |
| `used_at` | `DateTime` | `NEVER_USED` sentinel = valid; real timestamp = consumed |
| `created_at` | `DateTime` | |

### Model `AuthorizationCode` (Short-lived, 60 s TTL)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `Integer`, PK, autoincrement | |
| `code` | `String(255)`, Unique, Index | `secrets.token_urlsafe(32)` |
| `client_id` | `String(255)` | |
| `user_id` | `String(255)` | |
| `redirect_uri` | `Text` | Must match the request |
| `scope` | `String(255)` | e.g. `openid` |
| `nonce` | `String(255)`, nullable | Optional (OIDC Core §3.1.2.1) |
| `code_challenge` | `String(255)` | PKCE: SHA256(code_verifier), Base64URL |
| `code_challenge_method` | `String(10)` | Always `S256` |
| `auth_time` | `Integer` | Unix timestamp of 2FA verification |
| `expires_at` | `DateTime`, Index | 60 second TTL |
| `used` | `Boolean`, default=False | Single-use |

### Model `SigningKey` (EC key pair for ID token)

| Field | Type | Description |
|-------|------|-------------|
| `id` | `Integer`, PK, autoincrement | |
| `kid` | `String(255)`, Unique | Key ID (16 hex characters) |
| `private_key_encrypted` | `LargeBinary` | Fernet-encrypted with SECRET_KEY |
| `public_key_pem` | `Text` | Plaintext; published in JWKS |
| `algorithm` | `String(10)` | `ES256` |
| `active` | `Boolean`, default=True | Key rotation |
| `created_at` | `DateTime` | |
| `expires_at` | `DateTime` | `NEVER_EXPIRES` sentinel for unlimited keys |

### Model `AuditLog`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `Integer`, PK, autoincrement | |
| `user_id` | `String(255)`, Index | |
| `action` | `String(50)`, Index | `setup` / `verify` / `fail` |
| `method` | `String(50)` | `webauthn_platform` / `webauthn_roaming` / `totp` / `backup` |
| `ip_hash` | `String(64)` | `SHA256(ip + SECRET_SALT)` — no plaintext stored (GDPR) |
| `timestamp` | `DateTime`, Index | UTC |

---

## 9. Security Concept

### Trust Boundaries

| Zone | Data | Protections |
|------|------|-------------|
| **Secure Enclave/TPM/HSM** | Private keys (FIDO2) | Hardware-encrypted, never exportable |
| **Main application** | Client private key | Stored locally (encrypted filesystem or HSM), never over the network |
| **Browser** | Challenge, assertion, TOTP codes | CSP `default-src 'none'; script-src 'nonce-{random}';`, inline JS only |
| **Flask backend** | Public keys, encrypted secrets | SQLAlchemy ORM, Fernet encryption before DB writes |
| **Transport** | JWTs, WebAuthn data | TLS 1.3 (externally terminated), mTLS for token endpoint |

### Security Measures

1. **No shared secrets:** Client authentication exclusively via X.509 certificates (mTLS) or private_key_jwt. No `client_secret` strings in the database.

2. **Certificate pinning:** Main application validates X2FA certificate on JWKS retrieval (hardcoded fingerprint or trust store).

3. **CSP header:**
   `Content-Security-Policy: default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; form-action 'self' https; base-uri 'none'; frame-ancestors 'none';`

4. **HSTS:**
   `Strict-Transport-Security: max-age=31536000; includeSubDomains` — required, prevents SSL stripping.

5. **TOTP encryption:** Fernet with key derived from `SHA256(SECRET_KEY)`.

6. **TOTP replay:** Check `last_used_at`. Identical code in the same 30 s window is rejected.

7. **Rate limiting** — IP-based, moving-window, for all security-critical endpoints.

8. **FIDO2 replay:** Strict sign-count increment.

9. **PKCE S256 (RFC 7636):** Mandatory for all Authorization Code requests. `plain` explicitly rejected.

10. **OIDC security:**
    - Authorization code: 60 s TTL, single-use
    - ID token: ES256, 60 s TTL, optional `nonce` binding
    - `redirect_uri`: exact string match
    - `state` parameter: CSRF protection (relying party's responsibility)
    - `iss` claim: relying party checks against configured issuer URL

11. **Key rotation:**
    - JWKS contains the active key plus older keys in the overlap window
    - Rotation via CLI: `flask init-keys`
    - Client certificates: 90-day validity, automatic renewal workflows possible

12. **DB security:** SQLite (0600), PostgreSQL (SSL mode require), prepared statements.

13. **Backup code entropy:** `secrets.token_hex(4).upper()` = 8 hex characters (32 bits = 4 billion combinations). This is the **user-facing input format**. The database stores only the bcrypt hash (`String(255)`, rounds=12) — the plaintext code is never persisted.

14. **IP anonymization:** `SHA256(ip + SECRET_SALT)` in AuditLog.

---

## 10. OIDC Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/.well-known/openid-configuration` | GET | Discovery document (RFC 8414) |
| `/.well-known/jwks.json` | GET | X2FA public key set (RFC 7517) |
| `/authorize` | GET | Starts Authorization Code Flow |
| `/token` | POST | Exchange code for ID token (mTLS or private_key_jwt) |
| `/setup` | GET | Method selection (WebAuthn / TOTP) |
| `/setup/complete` | POST | Complete FIDO2 registration |
| `/totp/setup` | GET | Show TOTP QR code |
| `/totp/setup/verify` | POST | Confirm TOTP setup |
| `/totp/verify` | GET/POST | Enter and verify TOTP code |
| `/backup/verify` | GET/POST | Enter and verify backup code |
| `/done` | GET | Demo callback (demo RP only) |

### Discovery Document

```json
{
  "issuer": "https://x2fa.example.com",
  "authorization_endpoint": "https://x2fa.example.com/authorize",
  "token_endpoint": "https://x2fa.example.com/token",
  "jwks_uri": "https://x2fa.example.com/.well-known/jwks.json",
  "response_types_supported": ["code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["ES256"],
  "scopes_supported": ["openid", "app:setup"],
  "token_endpoint_auth_methods_supported": ["tls_client_auth", "private_key_jwt"],
  "code_challenge_methods_supported": ["S256"],
  "grant_types_supported": ["authorization_code"],
  "claims_supported": ["sub", "iss", "aud", "exp", "iat", "auth_time", "nonce"]
}
```

### OIDC Authorization Code Flow (Self-Sovereign)

```mermaid
sequenceDiagram
    participant App as Main application
    participant Key as Private key (local)
    participant Cert as X.509 certificate
    participant Browser as Browser
    participant TLS as TLS layer (mTLS)
    participant X2FA as X2FA OIDC provider
    participant CA as Trusted CA

    App->>App: generate client_id, state, nonce<br/>+ PKCE (code_verifier, code_challenge)
    App->>Browser: 302 → /authorize?client_id=...&code_challenge=...&state=...
    Browser->>X2FA: GET /authorize
    X2FA->>X2FA: validate client_id, redirect_uri
    X2FA->>Browser: 2FA dialog (WebAuthn / TOTP / Backup)
    Browser->>X2FA: complete 2FA
    X2FA->>X2FA: generate authorization code (60 s TTL)
    X2FA->>Browser: 302 → redirect_uri?code=ABC&state=...
    Browser->>App: code + state
    App->>App: verify state (CSRF protection)
    
    Note over App,X2FA: Token request with mTLS
    
    App->>TLS: POST /token<br/>grant_type=authorization_code<br/>&code=ABC<br/>&code_verifier=...<br/>+ client certificate in TLS handshake
    TLS->>X2FA: forward with X-Client-Certificate header
    X2FA->>CA: validate certificate<br/>(signature, CN=client_id, validity)
    CA->>X2FA: ✅ valid
    X2FA->>X2FA: validate code (TTL, PKCE, redirect_uri, single-use)
    X2FA->>App: ID token (ES256-signed)
    
    App->>X2FA: GET /.well-known/jwks.json (TLS + pinning)
    X2FA->>App: JWKS (OP public keys)
    App->>App: verify ID token<br/>(nonce, iss, aud, sub, exp)
```

---

## 11. Communication Diagrams

### 11.1 FIDO2 Setup (Cross-Platform, all authenticators)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Main app
    participant X2FA as X2FA service
    participant DB as Database
    participant Auth as Authenticator<br/>(FaceID/YubiKey/Phone)

    User->>App: Login with password
    App->>App: 2FA not set up
    App->>App: generate JWT (sub: user123, action: setup, return_url: ..., exp: +5 min)
    App->>User: 302 redirect → 2fa.example.com/setup?token=JWT

    User->>X2FA: GET /setup?token=JWT
    X2FA->>X2FA: validate JWT
    X2FA->>X2FA: generate challenge (32 bytes)
    X2FA->>DB: persist challenge (expires_at: +5 min, used: false)

    Note over X2FA: NO authenticatorAttachment restriction<br/>(cross-platform default)
    X2FA->>User: HTML + inline JS<br/>(CSP nonce, challenge, detection JS)

    Note over User: Detection:<br/>- Platform available? → FaceID button<br/>- Otherwise → "insert YubiKey" or "scan with smartphone"

    User->>User: navigator.credentials.create()
    User->>Auth: challenge + RP ID (2fa.example.com)

    Note over Auth: Depends on authenticator:<br/>- FaceID: biometrics check<br/>- YubiKey: touch<br/>- Phone: hybrid/QR

    Auth->>Auth: generate key pair (private in hardware)
    Auth->>User: credential ID + public key + attestation + transport info

    User->>X2FA: POST /setup/complete<br/>(credential_id, attestation, transport, token)

    X2FA->>DB: validate challenge (unused, not expired)
    X2FA->>X2FA: verify_registration_response()

    X2FA->>DB: INSERT credential<br/>(transport: 'usb'|'nfc'|'internal'|'hybrid',<br/>authenticator_type: 'platform'|'roaming')

    Note over X2FA: generate 10 backup codes<br/>bcrypt hash, persist

    X2FA->>X2FA: return JWT<br/>(result: success, amr: ["webauthn_platform"] or ["webauthn_roaming"])

    X2FA->>User: 302 redirect → app/callback?token=ReturnJWT
    User->>App: receive callback
    App->>User: 2FA active + show backup codes (once)
```

### 11.2 FIDO2 Verify (Multi-Device)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Main app
    participant X2FA as X2FA service
    participant DB as Database
    participant Auth as Authenticator<br/>(device X)

    User->>App: Login with password
    App->>App: 2FA required
    App->>App: generate JWT (sub: user123, action: verify)
    App->>User: 302 redirect → 2fa.example.com/verify?token=JWT

    User->>X2FA: GET /verify?token=JWT
    X2FA->>DB: SELECT credentials WHERE user_id=123
    X2FA->>X2FA: generate challenge
    X2FA->>DB: persist challenge

    Note over X2FA: allowCredentials: all user keys<br/>(YubiKey, FaceID, hybrid)

    X2FA->>User: HTML + inline JS<br/>(challenge, allowCredentials: [{id, type, transports}])

    Note over User: User selects / is prompted:<br/>- FaceID (if available)<br/>- Insert YubiKey<br/>- Scan smartphone (hybrid)

    User->>User: navigator.credentials.get()
    User->>Auth: assertion request (with credential ID)

    Note over Auth: biometrics/PIN/touch depending on device

    Auth->>Auth: sign challenge
    Auth->>User: assertion

    User->>X2FA: POST /verify/complete<br/>(credential_id, assertion, authenticatorData, signature)

    X2FA->>DB: load credential (public key + sign count)
    X2FA->>X2FA: verify_authentication_response()<br/>+ sign count >= stored?

    X2FA->>DB: UPDATE sign_count += 1, last_used_at=now()

    X2FA->>X2FA: return JWT (verified: true, amr: ["webauthn_platform"] or ["webauthn_roaming"])

    X2FA->>User: 302 redirect → app/callback
    User->>App: callback → session → dashboard
```

### 11.3 TOTP Setup & Verify (Universal fallback)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Main app
    participant X2FA as X2FA service
    participant DB as Database
    participant Phone as TOTP app<br/>(smartphone)

    Note over User: Scenario: Linux desktop<br/>or legacy browser

    User->>App: set up 2FA
    App->>App: detection: no WebAuthn available<br/>or user selects manual method
    App->>User: redirect → 2fa.example.com/totp/setup?token=JWT

    User->>X2FA: GET /totp/setup?token=JWT
    X2FA->>X2FA: generate Base32 secret (32 random bytes)
    X2FA->>X2FA: Fernet-encrypt with X2FA_SECRET
    X2FA->>DB: INSERT TOTPSecret<br/>(user123, encrypted_secret, verified=0)

    X2FA->>X2FA: generate QR code<br/>otpauth://totp/X2FA:user123?secret=BASE32&issuer=X2FA

    X2FA->>User: HTML (QR code + secret as text + input field)

    User->>Phone: scan QR or enter secret manually
    Phone->>User: 6-digit code (e.g. 123456)

    User->>X2FA: POST /totp/setup/verify (code=123456)

    X2FA->>DB: load encrypted secret
    X2FA->>X2FA: decrypt → Base32
    X2FA->>X2FA: pyotp.TOTP(secret).verify("123456", valid_window=1)

    X2FA->>DB: UPDATE verified=1
    X2FA->>User: redirect → app (success)

    Note over User: Later: login with TOTP

    User->>App: login
    App->>User: redirect → /totp/verify

    User->>X2FA: GET /totp/verify
    X2FA->>User: input field (plain HTML)

    User->>Phone: read code (e.g. 654321)
    User->>X2FA: POST /totp/verify (code=654321)

    X2FA->>DB: load secret + check last_used_at (replay protection)
    X2FA->>X2FA: validate
    X2FA->>DB: last_used_at = now()

    X2FA->>User: return JWT (verified, amr: ["totp"]) → redirect
```

### 11.4 Backup Code Verify (Emergency)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Main app
    participant X2FA as X2FA service
    participant DB as Database

    Note over User: Device lost (iPhone with FaceID)<br/>New device has no key

    User->>App: login (password)
    App->>User: redirect → 2fa.example.com/verify

    User->>X2FA: GET /verify
    X2FA->>DB: look up credentials for browser<br/>(no match - new device)

    X2FA->>User: "No FIDO2 key for this device"<br/>link: "use backup code"

    User->>X2FA: GET /backup/verify?token=JWT
    X2FA->>User: input field: "8-character backup code"

    Note over User: code from printout: A1B2C3D4

    User->>X2FA: POST /backup/verify (code=A1B2C3D4)

    X2FA->>X2FA: bcrypt(code) with salt
    X2FA->>DB: SELECT * FROM backup_codes<br/>WHERE code_hash=HASH<br/>AND user_id=123<br/>AND used_at IS NULL

    alt Match found
        X2FA->>DB: UPDATE used_at=now()
        X2FA->>X2FA: return JWT (verified, amr: ["backup"], remaining: 9)
        X2FA->>User: redirect → app
        App->>User: "Emergency login OK. Please set up new 2FA IMMEDIATELY."
    else No match or already used
        X2FA->>User: 403 "Invalid or already used code"
    end
```

### 11.5 Hybrid Transport (Phone-as-Key for Linux)

```mermaid
sequenceDiagram
    participant Linux as Linux PC (Browser)
    participant X2FA as X2FA service
    participant Phone as Smartphone (Chrome/Safari)
    participant Auth as Phone authenticator<br/>(FaceID/fingerprint)

    Note over Linux: Linux desktop without TPM<br/>or user prefers phone

    Linux->>X2FA: GET /verify (or /setup)
    X2FA->>Linux: HTML shows:<br/>1. "Scan QR code with smartphone"<br/>2. "Or use YubiKey"

    Note over Linux,Phone: caBLE (Cloud Assisted BLE)<br/>or QR-based

    Linux->>X2FA: request: "start hybrid session"
    X2FA->>Linux: QR code (contains session ID + challenge)

    Phone->>Linux: camera scans QR
    Phone->>X2FA: connect (via Bluetooth or cloud relay)
    X2FA->>Phone: transmit challenge

    Phone->>Auth: WebAuthn request<br/>(FaceID on iPhone)
    Auth->>Phone: assertion signed

    Phone->>X2FA: transmit assertion<br/>(via caBLE/cloud)

    X2FA->>X2FA: validate as with normal WebAuthn
    X2FA->>Linux: "authenticated" (via WebSocket/SSE or polling)

    Linux->>X2FA: redirect/completion
    X2FA->>Linux: return JWT
    Linux->>App: callback

    Note over Linux: PC is logged in,<br/>authentication happened on phone
```

---

## 12. Admin CLI

```bash
# CA management
flask add-ca "inqbus-internal-ca" /path/to/ca_cert.pem
flask list-cas
flask revoke-ca "inqbus-internal-ca"

# Generate signing key (EC P-256, ES256)
flask init-keys

# Register OIDC client (with certificate)
flask add-client shop.example.com \
  --method tls_client_auth \
  --redirect-uri "https://shop.example.com/auth/callback" \
  --scopes "openid"

# OIDC client for private_key_jwt
flask add-client api.example.com \
  --method private_key_jwt \
  --redirect-uri "https://api.example.com/callback" \
  --jwks-uri "https://api.example.com/.well-known/jwks.json"

# List clients
flask list-clients

# Deactivate client
flask revoke-client shop.example.com

# Audit statistics
flask stats

# Clean up old authorization codes (>1 h, nonce-safe)
flask cleanup-codes

# Generate client certificate (for developers)
flask issue-client-cert shop.example.com \
  --ca "inqbus-internal-ca" \
  --validity-days 90 \
  --output ./certs/
```

---

## 13. User Perspective: Flows

### Scenario A: macOS/iOS (FaceID/TouchID)
Log in to main app → redirect to `2fa.example.com/setup` → iOS popup "Use FaceID?" → confirm → face scanned → 10 backup codes shown → done.

### Scenario B: Windows Hello (TPM)
Enter password → Windows Hello popup (fingerprint/PIN) → touch sensor → immediate redirect.

### Scenario C: Linux Desktop (Hybrid/Phone-as-Key)
Linux PC without TPM → after 2FA start: QR code ("scan with smartphone") → Android/iPhone camera opens, scans QR → FaceID on phone → PC logs in (via caBLE/cloud handshake).

### Scenario D: Linux Desktop (YubiKey)
Linux PC, YubiKey in USB → "touch YubiKey" → touch gold contact → signature completed → login.

### Scenario E: Legacy browser/headless (TOTP)
No WebAuthn available → redirect to `/totp/verify` → open Google Authenticator, enter 6-digit code → login.

### Scenario F: Lost device (backup codes)
Device lost → new device → link "use backup code" → enter 8-character hex code → login successful, code consumed (9 remaining) → app forces new 2FA setup.

---

## 14. Installation

### Option A: SQLite + Caddy (Zero-Config)

```bash
git clone <repo> /opt/x2fa && cd /opt/x2fa
uv sync

# Configuration
cat > src/x2fa/config_files/security_config.toml << EOF
[production]
SECRET_KEY  = "$(openssl rand -hex 32)"
SECRET_SALT = "$(openssl rand -hex 16)"
EOF

cat > src/x2fa/config_files/x2fa_config.toml << EOF
[production]
DOMAIN = "2fa.example.com"
TESTING = false
EOF

# Create and register internal CA
openssl req -x509 -newkey rsa:4096 -keyout /etc/x2fa/ca_key.pem \
  -out /etc/x2fa/ca_cert.pem -days 3650 -nodes \
  -subj "/C=US/O=MyOrg/CN=Internal-CA"
chmod 600 /etc/x2fa/ca_key.pem

 flask add-ca "internal-ca" /etc/x2fa/ca_cert.pem

# Initialize signing key
 flask init-keys

# Register first client (example)
 flask add-client "shop.example.com" \
  --method tls_client_auth \
  --redirect-uri "https://shop.example.com/auth/callback"

# Start
 gunicorn "x2fa.wsgi:app" --bind 127.0.0.1:5000
```

Caddyfile:
```caddy
2fa.example.com {
    reverse_proxy localhost:5000
    tls {
        # Automatic Let's Encrypt certificates
    }
}
```

### Option B: PostgreSQL + nginx + mTLS (Enterprise)

```bash
# Prepare PostgreSQL
sudo -u postgres createdb x2fa && sudo -u postgres createuser x2fa -P

# DB config
cat > src/x2fa/config_files/db_config.toml << EOF
[production]
SQLALCHEMY_DATABASE_URI = "postgresql://x2fa:password@localhost/x2fa"
EOF

# Rate limiting: Redis for distributed setup
cat >> src/x2fa/config_files/ratelimit_config.toml << EOF
[production]
RATELIMIT_STORAGE_URI = "redis://localhost:6379/0"
EOF

uv sync --extra postgres
 flask init-keys
 gunicorn "x2fa.wsgi:app" -w 4 --bind 127.0.0.1:5000
```

nginx configuration (with mTLS):
```nginx
server {
    listen 443 ssl http2;
    server_name 2fa.example.com;
    
    ssl_certificate     /etc/letsencrypt/live/2fa.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/2fa.example.com/privkey.pem;
    
    # Verify client certificates
    ssl_verify_client optional;
    ssl_client_certificate /etc/nginx/certs/ca_cert.pem;
    ssl_verify_depth 2;
    
    location /token {
        ssl_verify_client on;  # required for token endpoint
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Client-Certificate $ssl_client_cert;
        proxy_set_header X-Client-Verify $ssl_client_verify;
        proxy_set_header X-Client-DN $ssl_client_s_dn;
    }
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Option C: Generate a client certificate

```bash
# For the main application (shop.example.com)
CLIENT_ID="shop.example.com"

# Private key and CSR
openssl genrsa -out client_key.pem 2048
openssl req -new -key client_key.pem -out client.csr \
  -subj "/C=US/O=MyOrg/CN=${CLIENT_ID}"

# CA signs (on X2FA server or secure offline CA)
openssl x509 -req -in client.csr -CA /etc/x2fa/ca_cert.pem \
  -CAkey /etc/x2fa/ca_key.pem -CAcreateserial \
  -out client_cert.pem -days 90 -sha256

# Bundle for the app
cat client_key.pem client_cert.pem > client_bundle.pem
chmod 600 client_bundle.pem

# Delete client.csr (security precaution)
rm client.csr
```

Usage in the main application (Python):
```python
import requests

# mTLS
response = requests.post(
    "https://2fa.example.com/token",
    data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "code_verifier": pkce_verifier
    },
    cert=("./client_cert.pem", "./client_key.pem"),
    verify=True  # verify server certificate
)
```

---

## 15. Summary

| Aspect | Implementation |
|--------|---------------|
| **Authentication** | No shared secrets; X.509 certificates (mTLS) or private_key_jwt |
| **Trust anchor** | Internal CA (root certificate) registered in X2FA; client certificates signed by this CA |
| **Key management** | Automatic rotation of client certificates (90 days) and signing keys |
| **2FA methods** | FIDO2 (Platform, Roaming, Hybrid), TOTP, backup codes |
| **OIDC security** | PKCE S256 enforced, 60 s code TTL, ES256 ID tokens, nonce support |
| **Scalability** | PostgreSQL/MySQL, Redis for rate limiting, stateless token validation |