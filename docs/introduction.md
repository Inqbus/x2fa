# X2FA — Project Introduction

X2FA is a FIDO2 / TOTP microservice with an integrated OIDC provider. It provides
two-factor authentication (2FA) for relying parties (RPs) and supports six client
authentication methods — from PKI-based (mTLS, private_key_jwt) to shared-secret approaches.

## What does X2FA do?

X2FA acts as a central 2FA and OIDC identity provider:

1. **OIDC Authentication** — An RP redirects the user to the X2FA server,
   where the user authenticates with 2FA. After successful login, the RP
   receives an ES256-signed ID token.

2. **Two-Factor Authentication** — Users can authenticate with WebAuthn/FIDO2
   (Touch ID, Windows Hello, YubiKey), TOTP (authenticator app), or backup codes.

3. **Client Registration** — RPs are registered with one of six authentication methods:
   mTLS, private_key_jwt, self-signed TLS, client_secret_jwt,
   client_secret_post, client_secret_basic.

## Core Concepts

### OIDC Authorization Code Flow with PKCE

```mermaid
sequenceDiagram
    participant RP as Relying Party
    participant Browser as Browser
    participant X2FA as X2FA Server
    participant DB as Database

    RP->>Browser: 1. Redirect to /authorize
    Browser->>X2FA: GET /authorize?client_id=...&code_challenge=...&code_challenge_method=S256
    X2FA->>X2FA: Phase 1: Validate OIDC parameters
    X2FA->>DB: Store session parameters
    X2FA-->>Browser: 302 → /verify (Login) or /setup (Registration)
    Browser->>Browser: Perform 2FA (WebAuthn/TOTP/Backup)
    Browser->>X2FA: POST /verify/complete
    X2FA->>DB: Verify WebAuthn signature
    X2FA->>X2FA: session["2fa_verified"] = True
    X2FA-->>Browser: 302 → /authorize (Phase 2)
    Browser->>X2FA: GET /authorize (Phase 2)
    X2FA->>DB: Create authorization code (60s TTL)
    X2FA-->>RP: 302 → redirect_uri?code=...
    RP->>X2FA: POST /token?code=...&client_assertion=...
    X2FA->>DB: Authenticate client, sign ID token
    X2FA-->>RP: {id_token: "<ES256-JWT>"}
```

### Two-Phase Authorization

The `/authorize` endpoint operates in two phases:

1. **Phase 1** — OIDC parameters are validated and stored in the Flask session.
   The browser is redirected to the 2FA UI (`/verify` or `/setup`).
2. **Phase 2** — After successful 2FA (`session["2fa_verified"] = True`),
   Authlib creates the authorization code and redirects back to the RP.

This design keeps OIDC parameters out of URLs (no URL-based state).

### 2FA Methods

| Method | Description | Usage |
|--------|-------------|-------|
| **WebAuthn Platform** | Biometrics/TPM (Touch ID, Windows Hello) | Primary method |
| **WebAuthn Roaming** | USB/NFC/BLE (YubiKey, Nitrokey) | Primary method |
| **TOTP** | Time-based one-time passwords (authenticator app) | Fallback |
| **Backup Codes** | 10 single-use 8-character hex codes (bcrypt-hashed) | Emergency access |

### Client Authentication Methods

| Method | Type | Requires CA | Description |
|--------|------|-------------|-------------|
| `tls_client_auth` | PKI | Yes | mTLS — client certificate verified during TLS handshake |
| `private_key_jwt` | PKI | Yes | JWT client assertion with JWKS URI or x5c |
| `self_signed_tls_client_auth` | PKI | No | Self-signed certificate, fingerprint matching |
| `client_secret_jwt` | Shared Secret | No | JWT with HMAC signature (HS256) |
| `client_secret_post` | Shared Secret | No | Shared secret in POST body |
| `client_secret_basic` | Shared Secret | No | Shared secret in Basic-Auth header |

PKI methods (`tls_client_auth`, `private_key_jwt`) require a registered
Certificate Authority (CA). Shared-secret methods use a once-generated,
Fernet-encrypted secret.

## Technical Architecture

```mermaid
graph TB
    subgraph Frontend["Browser / RP"]
        SPA["SPA / Native App"]
    end

    subgraph Proxy["Reverse Proxy"]
        Nginx["nginx / Caddy"]
    end

    subgraph X2FA["X2FA Flask App"]
        subgraph Blueprints["Blueprints"]
            auth["auth_bp<br/>/authorize, /token, JWKS"]
            setup["setup_bp<br/>/setup/webauthn, /setup/complete"]
            verify["verify_bp<br/>/verify, /verify/complete"]
            totp["totp_bp<br/>/totp/setup, /totp/verify"]
            backup["backup_bp<br/>/backup/verify"]
        end

        subgraph OIDC["OIDC Server (Authlib)"]
            authorize["/authorize<br/>2-Phase Flow"]
            token["/token<br/>Token Exchange"]
            jwks["/.well-known/jwks.json<br/>Public Keys"]
            discovery["/.well-known/openid-configuration<br/>Discovery"]
        end

        subgraph Services["Services"]
            crypto["CryptoService<br/>Fernet + bcrypt"]
            webauthn["WebAuthn Helpers<br/>py_webauthn"]
            totp_h["TOTP Helpers<br/>pyotp + QR"]
        end

        subgraph Init["Extension Init"]
            config["config<br/>TOML Loader"]
            database["database<br/>SQLAlchemy"]
            limiter["limiter<br/>Rate Limiting"]
            security["security<br/>Secure Headers"]
            babel["babel<br/>i18n"]
        end
    end

    subgraph Storage["Storage"]
        DB["SQLite / PostgreSQL / MySQL"]
        Redis["Redis (optional)<br/>Rate Limiting"]
    end

    SPA --> Nginx
    Nginx --> X2FA

    auth --> authorize
    auth --> token
    auth --> jwks
    auth --> discovery

    setup --> webauthn
    verify --> webauthn
    totp --> totp_h
    backup --> crypto

    authorize --> crypto
    token --> crypto

    config --> DB
    database --> DB
    limiter --> Redis
```

### Layers

| Layer | Component | Technology |
|-------|-----------|------------|
| **Blueprints** | 5 route blueprints | Flask Blueprints |
| **OIDC Server** | Authlib integration | authlib 1.6+ |
| **Services** | Crypto, WebAuthn, TOTP | cryptography, py_webauthn, pyotp |
| **Extension Init** | Flask extensions | flask-sqlalchemy, flask-limiter, flask-babel |
| **Database** | SQLAlchemy ORM | SQLite (default), PostgreSQL, MySQL |

## Data Model

X2FA uses 8 SQLAlchemy models:

```mermaid
flowchart LR
    subgraph OIDC["OIDC"]
        OIDCClient["OIDCClient<br/>client_id (PK)<br/>redirect_uris<br/>token_endpoint_auth_method<br/>jwks_uri<br/>client_secret_encrypted"]
        AuthorizationCode["AuthorizationCode<br/>code (unique)<br/>client_id<br/>user_id<br/>nonce<br/>expires_at<br/>used"]
        SigningKey["SigningKey<br/>kid (unique)<br/>private_key_encrypted<br/>public_key_pem<br/>algorithm ES256<br/>active<br/>expires_at"]
    end

    subgraph Auth["Authentication"]
        Credential["Credential<br/>credential_id (PK)<br/>user_id<br/>public_key<br/>sign_count<br/>authenticator_type<br/>is_passkey<br/>last_used_at"]
        Challenge["Challenge<br/>challenge_id (PK)<br/>user_id<br/>challenge (bytes)<br/>expires_at<br/>used"]
        TOTPSecret["TOTPSecret<br/>user_id (PK)<br/>secret_encrypted<br/>verified<br/>last_used_at"]
        BackupCode["BackupCode<br/>code_hash (PK)<br/>user_id<br/>used_at"]
    end

    subgraph PKI["PKI"]
        TrustedCA["TrustedCA<br/>name (unique)<br/>cert_pem<br/>active<br/>expires_at"]
    end

    subgraph Audit["Audit"]
        AuditLog["AuditLog<br/>user_id<br/>action (setup/verify/fail)<br/>method<br/>ip_hash (SHA256)<br/>timestamp"]
    end

    OIDCClient -->|"OIDC Flow"| AuthorizationCode
    SigningKey -->|"signs"| AuthorizationCode
    Credential -->|"user_id"| AuditLog
    TOTPSecret -->|"user_id"| AuditLog
    BackupCode -->|"user_id"| AuditLog
    TrustedCA -.->|"validates"| OIDCClient
    Challenge -->|"user_id"| Credential
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **No shared secrets for mTLS/JWT** | PKI-based methods are more secure than shared secrets |
| **IP addresses hashed** | GDPR compliance — `SHA256(ip + X2FA_SECRET)` instead of plaintext |
| **Nonces kept in AuthorizationCodes** | Codes are not deleted after token exchange (only `used=True` marked). `cleanup-codes` removes them after 1h. This prevents the RP from being unable to process an ID token after 60s expiry. The real replay protection comes from the fact that the authorization code itself cannot be exchanged again (`used=True`). |
| **Sentinel values** | `NEVER_USED` (1970) and `NEVER_EXPIRES` (9999) as timezone-naive datetime values |
| **Session-based OIDC state** | No URL-based parameters — protection against log leakage |
| **Fernet encryption** | Symmetric encryption for secrets (client_secret, TOTP, SigningKey) |
| **bcrypt for backup codes** | 12 rounds, single-use, linear comparison |

## Configuration

X2FA uses XDG-compliant TOML configuration files:

```mermaid
graph LR
    subgraph XDG_Config["~/.config/x2fa/"]
        x2fa_config["x2fa_config.toml<br/>Domain, DB URI, OIDC"]
        security_config["security_config.toml<br/>SECRET_KEY, Session"]
        db_config["db_config.toml<br/>DB-specific"]
        ratelimit_config["ratelimit_config.toml<br/>Rate Limits"]
        babel_config["babel_config.toml<br/>i18n, Locale"]
    end

    subgraph XDG_Data["~/.local/share/x2fa/"]
        ca_key["ca_key.pem<br/>CA Private Key"]
        ca_cert["ca_cert.pem<br/>CA Certificate"]
        db_file["db.sqlite<br/>Database"]
        installer_session["installer_session.json<br/>Installer State"]
    end

    XDG_Config --> X2FA
    XDG_Data --> X2FA

    X2FA["X2FA App"]
```

Override with `X2FA_HOME`:

```bash
X2FA_HOME=/tmp/x2fa-test FLASK_APP=x2fa.wsgi:app uv run flask run
```

## Installer

The X2FA installer is a Textual-based TUI (Text User Interface) that walks
the user through the complete setup process:

```mermaid
flowchart LR
    MainMenu["MainMenuScreen"] --> Welcome["WelcomeScreen<br/>Preflight Checks"]
    Welcome --> Database["DatabaseScreen<br/>SQLite/Postgres/MySQL"]
    Database --> Domain["DomainScreen<br/>Hostname, Proxy Type"]
    Domain --> Security["SecurityScreen<br/>Secret Keys, Redis"]
    Security --> CAScreen{"PKI Method?"}
    CAScreen -- Yes --> CASetup["CAScreen<br/>Generate/Import CA"]
    CAScreen -- No --> Client["ClientScreen<br/>OIDC Client Config"]
    CASetup --> Client
    Client --> Review["ReviewScreen<br/>Config Summary"]
    Review --> Execute["ExecuteScreen<br/>Write Config, Init DB"]
    Execute --> Summary["SummaryScreen<br/>Start Command, Proxy Snippet"]

    MainMenu --> CAManage["CAManageScreen<br/>CA Management"]
    MainMenu --> Quit["Quit"]
```

The installer:
- Generates TOML configuration files
- Initializes the database (Alembic migrations)
- Creates ES256 signing keys
- Generates/imports CA certificates
- Registers the first OIDC client
- Issues client certificates (for PKI methods)

## Security

| Feature | Implementation |
|---------|----------------|
| **PKCE S256 mandatory** | `plain` is explicitly rejected |
| **ES256 ID tokens** | EC P-256 signatures, public keys via JWKS |
| **SSL verification** | JWKS fetch with `ssl.CERT_REQUIRED` + `check_hostname` |
| **Rate limiting** | Per-endpoint configurable, Redis for multi-worker |
| **Path traversal protection** | `_resolve_file()` validates all file paths |
| **Race condition prevention** | `call_from_thread` in ExecuteScreen, EAFP instead of `os.access()` |
| **Subprocess timeout** | 120s timeout for all Flask CLI calls |
| **Sign count regression** | Detection of cloned authenticators |
| **TOTP anti-replay** | 30-second window, `last_used_at` check |
| **Backup code hashing** | bcrypt with 12 rounds, single-use |
| **Secrets encryption** | Fernet (AES-128-CBC) for client_secret, TOTP, SigningKey |

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Unit tests only (no DB, no I/O)
uv run pytest tests/ -m unit -v

# Single test
uv run pytest tests/test_file.py::test_name -v

# E2E tests
uv run pytest tests/e2e/ -v
```

29 unit tests + E2E tests for the installer.

## Quick Reference

| Task | Command |
|------|---------|
| Initialize database | `FLASK_APP=x2fa.wsgi_cli:app uv run flask init-db` |
| Create signing keys | `FLASK_APP=x2fa.wsgi_cli:app uv run flask init-keys` |
| Register OIDC client | `FLASK_APP=x2fa.wsgi_cli:app uv run flask add-client <id> <uri> [--method <method>]` |
| Add CA | `FLASK_APP=x2fa.wsgi_cli:app uv run flask add-ca <name> <cert>` |
| Issue client cert | `FLASK_APP=x2fa.wsgi_cli:app uv run flask issue-client-cert <id> --ca <name>` |
| Apply migrations | `FLASK_APP=x2fa.wsgi_cli:app uv run flask db-upgrade` |
| Cleanup | `FLASK_APP=x2fa.wsgi_cli:app uv run flask cleanup-codes` |

## Documentation Structure

| File | Content |
|------|---------|
| `getting-started.md` | Installation, quickstart, configuration |
| `architecture.md` | System design, request flows, data models, session management |
| `cli-reference.md` | All Flask CLI commands, path resolution, security features |
| `oidc-auth.md` | OIDC discovery, 6 auth methods, authorization/token endpoint, 2FA flows |
| `installer.md` | Textual TUI, screens, InstallConfig, preflight checks |
| `security.md` | Cryptography, audit logging, WebAuthn security, PKCE, rate limiting |