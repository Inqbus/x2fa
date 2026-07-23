# X2FA — FIDO2 Microservice with OIDC Provider

X2FA is a standalone two-factor authentication microservice that exposes a standard **OpenID Connect (OIDC) Authorization Code Flow** to existing applications. After registering as an OIDC client, a relying party simply redirects users to X2FA for 2FA verification and receives a signed ID token in return.

**Supported second factors:**
- **WebAuthn / FIDO2** — Passkeys (FaceID, TouchID, Windows Hello), YubiKey, Nitrokey, phone-as-key (hybrid), any FIDO2-compatible authenticator
- **TOTP** — Google Authenticator, Aegis, FreeOTP, Authy, and any RFC 6238-compatible app
- **Backup codes** — 10 single-use codes generated at setup time

**Client authentication:** X2FA supports **six authentication methods** at the token endpoint:

| Method | Trust Model | Secret? | Recommended |
|---|---|---|---|
| `tls_client_auth` | CA-signed mTLS | No | **Yes** |
| `private_key_jwt` | JWKS-verified JWT | No | Yes |
| `self_signed_tls_client_auth` | Fingerprint-pinned cert | No | Acceptable |
| `client_secret_jwt` | HMAC-signed JWT | Yes (encrypted) | With caution |
| `client_secret_post` | Secret in POST body | Yes (encrypted) | No (production) |
| `client_secret_basic` | HTTP Basic auth | Yes (encrypted) | No (production) |

Client certificates are issued using the built-in CA management CLI. For secret methods, the installer generates and displays a secret once (never stored).

---

## Table of Contents

1. [Architecture](#architecture)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [First-Time Setup](#first-time-setup)
6. [OIDC Integration Guide](#oidc-integration-guide)
7. [API Reference](#api-reference)
8. [CLI Reference](#cli-reference)
9. [Development & Testing](#development--testing)
10. [Security Considerations](#security-considerations)
11. [Production Deployment](#production-deployment)

---

## Architecture

```
Relying Party (RP)                X2FA                         Browser
     │                              │                               │
     │── GET /authorize ────────────▶│                               │
     │   client_id, login_hint,      │── 302 /verify ───────────────▶│
     │   code_challenge (S256)       │                               │
     │                              │◀── WebAuthn / TOTP / Backup ──│
     │                              │                               │
     │                              │── 302 /authorize (phase 2) ──▶│
     │                              │── 302 redirect_uri?code=… ───▶│
     │◀── code ─────────────────────│                               │
     │                              │                               │
     │── POST /token ───────────────▶│                               │
     │   code, code_verifier,        │                               │
     │   client_assertion (JWT/x5c)  │                               │
     │◀── { id_token (ES256) } ─────│                               │
```

**Key design decisions:**
- **No shared secrets** — client authentication is certificate-based only (`tls_client_auth` or `private_key_jwt`). There are no `client_secret` values anywhere.
- **Self-Sovereign Keys** — each relying party holds its own private key; X2FA only stores trusted CA certificates and verifies presented certificates against them.
- **PKCE S256 mandatory** — `plain` is explicitly rejected. No exceptions.
- **ES256 ID tokens** — asymmetric EC P-256 keys; relying parties verify signatures using the public JWKS endpoint.
- **Stateless access tokens** — authorization codes are persisted for 60 seconds (nonce-protected for 1 hour); no token storage in the database.

### Directory Layout

```
x2fa/
├── src/x2fa/
│   ├── app.py               # Main app factory (with routes)
│   ├── app_cli.py           # Minimal app factory (CLI commands)
│   ├── wsgi.py              # WSGI entry point for app
│   ├── wsgi_cli.py          # WSGI entry point for CLI
│   ├── cli.py               # Flask CLI commands
│   ├── constants.py         # Shared constants (auth methods, sentinels, …)
│   ├── model/               # SQLAlchemy models (split by domain)
│   ├── oidc/                # Authlib OIDC server
│   ├── routes/              # Blueprints (auth, setup, verify, totp, backup)
│   ├── init_app/            # App-factory helpers (config, db, security, …)
│   ├── helpers/             # Helper utilities (attr_dict, config_pool, …)
│   └── services/            # Business logic (crypto, …)
├── src/x2fa/config_files/   # Template config files (.toml.default)
├── demo_rp/                 # Demo relying party for manual testing
├── docs/                    # Architecture docs and migration guides
├── tests/                   # pytest test suite
└── pyproject.toml
```

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A reverse proxy with TLS (nginx, Caddy, Traefik, …)
- SQLite (default), PostgreSQL, or MySQL

---

## Installation

```bash
git clone https://github.com/Inqbus/x2fa/
cd x2fa
uv sync
```

---

## Configuration

Configuration is managed via plain TOML files. The installer creates config files
in `~/.config/x2fa/` (or `X2FA_CONFIG_ROOT` if set).

### Key Settings (`x2fa_config.toml`)

| Setting | Description | Example |
|---|---|---|
| `SECRET_KEY` | Master secret ≥ 32 chars (Fernet key + session signing) | `openssl rand -hex 32` |
| `DOMAIN` | Public domain of this X2FA instance | `2fa.example.com` |
| `ORIGIN` | WebAuthn origin (override for local dev) | `http://localhost:5000` |

### Database (`db_config.toml`)

| Setting | Default | Description |
|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | `sqlite:///x2fa.db` | SQLAlchemy database URI |

Override any setting via environment variables prefixed with `X2FA_` or `X2FA_DATABASE_`:

```bash
export X2FA_SECRET_KEY=$(openssl rand -hex 32)
export X2FA_DOMAIN=2fa.example.com
export X2FA_DATABASE__SQLALCHEMY_DATABASE_URI=postgresql://...
```

---

## First-Time Setup

### Using the Interactive Installer (Recommended)

```bash
uv run x2fa-install
```

The installer walks through all configuration steps and sets up X2FA automatically:
1. Preflight checks — Python ≥ 3.11, uv, port 5000, Redis (optional)
2. Database — SQLite (default), PostgreSQL, or MySQL
3. Domain & Proxy — public hostname and reverse proxy type
4. Security — auto-generates `SECRET_KEY` and `SECRET_SALT`
5. First OIDC Client — choose one of six auth methods
6. Certificate Authority (PKI methods only) — generate or import a CA
7. Review and execute

### Manual Setup

```bash
export FLASK_APP=x2fa.wsgi_cli:app

# 1. Create database tables
flask init-db

# 2. Generate EC signing key for ID tokens
flask init-keys

# 3. Create a CA for signing client certificates
#    (use any existing CA or generate a self-signed one with openssl)
flask add-ca my-ca /path/to/ca.cert.pem

# 4. Issue a client certificate for your relying party
flask issue-client-cert myapp --ca my-ca --output /path/to/certs/

# 5. Register the OIDC client
flask add-client myapp https://myapp.example.com/callback

# 6. Start the server
uv run flask run --port 5000
```

---

## OIDC Integration Guide

### Step 1 — Issue a Client Certificate

```bash
# Register your CA (once per CA)
flask add-ca my-ca /path/to/ca.cert.pem

# Issue a certificate for your relying party
flask issue-client-cert myapp --ca my-ca --output ./certs/
# Writes: certs/myapp.key.pem (mode 0600), certs/myapp.cert.pem, certs/myapp.ca.pem
```

### Step 2 — Register a Client

```bash
# tls_client_auth (default) — certificate presented via reverse proxy header
flask add-client myapp https://myapp.example.com/callback

# private_key_jwt — client signs a JWT with the private key, embeds cert in x5c header
flask add-client myapp https://myapp.example.com/callback \
  --method private_key_jwt \
  --jwks-uri https://myapp.example.com/.well-known/jwks.json
```

### Step 3 — Authorization Request

Redirect the user to X2FA with these parameters:

```
GET https://2fa.example.com/authorize
  ?client_id=myapp
  &redirect_uri=https://myapp.example.com/callback
  &response_type=code
  &scope=openid
  &state=<random_state>
  &nonce=<random_nonce>
  &login_hint=<user_id>
  &code_challenge=<S256_hash>
  &code_challenge_method=S256
```

**`login_hint`** carries the user identifier that X2FA uses to look up existing 2FA credentials. It appears as `sub` in the ID token.

**`scope=openid app:setup`** triggers the setup flow (credential registration) instead of verification.

**PKCE** is mandatory. Generate the code pair:
```python
import secrets, hashlib, base64
code_verifier  = secrets.token_urlsafe(43)
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b'=').decode()
```

### Step 4 — Handle the Callback

X2FA redirects to your `redirect_uri` with:
```
GET https://myapp.example.com/callback?code=<auth_code>&state=<state>
```

Verify `state` matches what you sent.

### Step 5 — Exchange Code for Tokens

#### Using `tls_client_auth`

The reverse proxy must forward the client certificate as a PEM-encoded header:

```nginx
# nginx
proxy_set_header X-Client-Certificate $ssl_client_escaped_cert;
```

```bash
POST https://2fa.example.com/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<auth_code>
&redirect_uri=https://myapp.example.com/callback
&client_id=myapp
&code_verifier=<code_verifier>
```

#### Using `private_key_jwt`

Build a signed JWT with the client certificate embedded as `x5c` in the header:

```python
import base64, time, secrets
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from authlib.jose import JsonWebKey, jwt as jose_jwt

cert_pem = open("certs/myapp.cert.pem", "rb").read()
key_pem  = open("certs/myapp.key.pem",  "rb").read()

cert    = x509.load_pem_x509_certificate(cert_pem)
cert_b64 = base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()

now    = int(time.time())
claims = {
    "iss": "myapp", "sub": "myapp",
    "aud": "https://2fa.example.com/token",
    "exp": now + 60, "iat": now,
    "jti": secrets.token_urlsafe(16),
}
jwk   = JsonWebKey.import_key(key_pem)
token = jose_jwt.encode({"alg": "ES256", "x5c": [cert_b64]}, claims, jwk)
```

```bash
POST https://2fa.example.com/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<auth_code>
&redirect_uri=https://myapp.example.com/callback
&client_id=myapp
&code_verifier=<code_verifier>
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion=<signed_jwt>
```

**Response:**
```json
{
  "access_token": "…",
  "token_type": "Bearer",
  "expires_in": 864000,
  "scope": "openid",
  "id_token": "<ES256-signed JWT>"
}
```

### Step 6 — Verify the ID Token

```python
from authlib.jose import JsonWebKey, jwt
import requests

jwks   = requests.get("https://2fa.example.com/.well-known/jwks.json").json()
key    = JsonWebKey.import_key_set(jwks)
claims = jwt.decode(id_token, key)
claims.validate()

assert claims["iss"] == "https://2fa.example.com"
assert claims["aud"] == "myapp"
assert claims["sub"] == expected_user_id
assert claims["nonce"] == nonce_you_sent
```

### ID Token Claims

| Claim | Type | Description |
|---|---|---|
| `sub` | string | User identifier (value of `login_hint`) |
| `iss` | string | `https://<DOMAIN>` |
| `aud` | string | `client_id` |
| `exp` | int | Expiry (60 seconds after issuance) |
| `iat` | int | Issued-at timestamp |
| `auth_time` | int | Unix timestamp of 2FA completion |
| `nonce` | string | Echoed nonce for replay protection |

---

## API Reference

### `GET /.well-known/openid-configuration`

OIDC Discovery document.

### `GET /.well-known/jwks.json`

JSON Web Key Set with the active EC public key(s) for ID token verification.

### `GET /authorize`

**OIDC Authorization Endpoint.**

| Parameter | Required | Description |
|---|---|---|
| `client_id` | Yes | Registered client identifier |
| `redirect_uri` | Yes | Must match a registered redirect URI |
| `response_type` | Yes | Must be `code` |
| `scope` | Yes | Must include `openid`; add `app:setup` for registration flow |
| `login_hint` | Yes | User identifier to authenticate |
| `code_challenge` | Yes | PKCE S256 challenge |
| `code_challenge_method` | Yes | Must be `S256` |
| `state` | Recommended | Opaque string echoed in redirect |
| `nonce` | Recommended | Random value for replay protection |

### `POST /token`

**OIDC Token Endpoint.** Exchanges an authorization code for tokens.

Supported client authentication methods: `tls_client_auth`, `private_key_jwt`.

### `GET /setup`, `POST /setup/complete`, `GET /setup/done`

WebAuthn credential registration flow.

### `GET /verify`, `POST /verify/complete`

WebAuthn assertion flow. Falls back to `/totp/verify` if no WebAuthn credentials exist.

### `GET /totp/setup`, `POST /totp/setup/verify`

TOTP provisioning flow.

### `GET /totp/verify`, `POST /totp/verify`

TOTP verification with replay protection.

### `GET /backup/verify`, `POST /backup/verify`

Backup code verification.

---

## CLI Reference

```bash
export FLASK_APP=x2fa.wsgi_cli:app
```

### `flask init-db`

Creates all database tables. Safe to run on a fresh database.

### `flask init-keys`

Generates a new EC P-256 signing key pair for ID token signing (ES256). Deactivates all previously active keys.

```bash
flask init-keys
# Signing key generated: kid=e44bbe26ab12dfce
```

### `flask add-ca <name> <cert_path>`

Registers a trusted CA certificate used to validate client certificates.

```bash
flask add-ca my-org-ca /etc/ssl/my-org-ca.cert.pem
# CA registered:  my-org-ca
# Expires:        2027-01-01
# Fingerprint:    AA:BB:CC:…
```

### `flask list-cas`

Lists all registered CA certificates with name, status, expiry, and fingerprint. Warns if any active CA is expired or expires within 30 days.

### `flask revoke-ca <name>`

Deactivates a CA (sets `active=False`). The record is kept for audit purposes. Clients authenticated via this CA will no longer be accepted.

### `flask issue-client-cert <client_id>`

Issues a client certificate signed by the named CA.

```bash
flask issue-client-cert myapp --ca my-org-ca --output ./certs/
# Writes: certs/myapp.key.pem (0600), certs/myapp.cert.pem, certs/myapp.ca.pem
```

Options:
- `--ca` — name of the signing CA (required)
- `--validity-days` — certificate lifetime in days (default: 90)
- `--output` — output directory (default: current directory)

### `flask add-client <client_id> <redirect_uri>`

Registers a new OIDC client.

```bash
# tls_client_auth (default) — CA-signed mTLS
flask add-client myapp https://myapp.example.com/callback

# private_key_jwt — JWKS-verified JWT
flask add-client myapp https://myapp.example.com/callback \
  --method private_key_jwt \
  --jwks-uri https://myapp.example.com/.well-known/jwks.json

# self_signed_tls_client_auth — fingerprint-pinned self-signed cert
flask add-client myapp https://myapp.example.com/callback \
  --method self_signed_tls_client_auth \
  --cert /path/to/self_signed.pem

# client_secret_jwt — HMAC-signed JWT (auto-generates secret)
flask add-client myapp https://myapp.example.com/callback \
  --method client_secret_jwt

# client_secret_post — secret in POST body (auto-generates secret)
flask add-client myapp https://myapp.example.com/callback \
  --method client_secret_post

# client_secret_basic — HTTP Basic auth (auto-generates secret)
flask add-client myapp https://myapp.example.com/callback \
  --method client_secret_basic
```

Options:
- `--method` — `tls_client_auth`, `private_key_jwt`, `self_signed_tls_client_auth`, `client_secret_jwt`, `client_secret_post`, or `client_secret_basic`
- `--jwks-uri` — JWKS URL (required for `private_key_jwt`)
- `--cert` — Path to self-signed certificate (required for `self_signed_tls_client_auth`)
- `--scopes` — allowed scopes (default: `openid app:setup`)

For secret methods (`client_secret_jwt`, `client_secret_post`, `client_secret_basic`), a 64-character random secret is auto-generated and displayed exactly once. Record it immediately — it cannot be retrieved later.

### `flask list-clients`

Lists all registered OIDC clients with status and auth method.

### `flask revoke-client <client_id>`

Deactivates an OIDC client.

### `flask stats`

Displays audit log statistics and current credential counts.

### `flask cleanup-codes`

Deletes authorization codes older than 1 hour. Safe to run as a cron job.

---

## Development & Testing

### Run Locally

```bash
export FLASK_APP=x2fa.wsgi_cli:app

uv run flask init-db
uv run flask init-keys

# Set up a CA and issue a client cert for the demo RP
# (if using PKI auth method)
uv run flask add-ca demo-ca /path/to/ca.cert.pem
uv run flask issue-client-cert demo-rp --ca demo-ca --output demo_rp/

# Choose your auth method (default: tls_client_auth)
uv run flask add-client demo-rp http://localhost:5001/callback

# The installer creates demo_rp_settings.toml with the correct auth method
# For secret methods, edit to add the secret:
# CLIENT_SECRET = "your-64-char-secret"

uv run flask run --port 5000
# In a second terminal:
uv run python demo_rp/app.py
```

### Running Tests

```bash
uv run pytest tests/ -v
```

### Demo Relying Party

The demo RP (`demo_rp/app.py`) simulates an OIDC relying party for testing the full auth flow. It supports **all six authentication methods** and automatically configures itself based on the installed auth method.

**Setup (once per auth method):**
```bash
# The installer creates demo_rp_settings.toml with the correct auth method

# For secret methods, edit to add the secret:
# CLIENT_SECRET = "your-64-char-secret"

uv run python demo_rp/app.py
```

Open `http://localhost:5001` in a browser, click **Verify 2FA** or **Setup 2FA** to test the flow.

See `demo_rp/demo_rp_settings.toml` for example configurations for all auth methods.

---

## Security Considerations

### Certificate-Based Client Authentication

X2FA does not support shared `client_secret` values. Every OIDC client must authenticate using a certificate issued by a CA registered with `flask add-ca`. This eliminates the risk of secret leakage and enables client identity to be verified cryptographically.

For `tls_client_auth`, the TLS termination proxy (nginx, Caddy, …) must be configured to request a client certificate and forward it to X2FA via the `X-Client-Certificate` header:

```nginx
ssl_client_certificate /etc/ssl/trusted-ca.pem;
ssl_verify_client on;
proxy_set_header X-Client-Certificate $ssl_client_escaped_cert;
```

### PKCE S256 Enforcement

`plain` code challenge method is explicitly rejected. This prevents PKCE downgrade attacks.

### Nonce Replay Protection

Nonces are stored in the `authorization_code` table. The `cleanup-codes` command only deletes codes older than **1 hour**, ensuring that nonces from recently-issued ID tokens (60-second expiry) cannot be replayed.

### Rate Limiting

| Endpoint | Limit |
|---|---|
| `/totp/setup/verify` | 5/min, 20/hour |
| `/totp/verify` | 5/min, 20/hour |
| `/verify/complete` | 10/min, 30/hour |
| `/backup/verify` | 3/min per IP |
| `/authorize` | 10/min, 100/hour |
| `/token` | 20/min |

### Signing Key Rotation

Run `flask init-keys` to generate a new key and deactivate the old one. The old public key remains in the JWKS endpoint, allowing relying parties to verify tokens issued before the rotation.

### Content Security Policy

Every response includes a per-request CSP nonce. The `script-src` directive only allows scripts with the matching nonce, preventing inline XSS.

---

## Production Deployment

### Example: gunicorn + nginx

**`/etc/systemd/system/x2fa.service`:**
```ini
[Unit]
Description=X2FA OIDC Microservice
After=network.target

[Service]
User=x2fa
WorkingDirectory=/opt/x2fa
EnvironmentFile=/opt/x2fa/.env
ExecStart=/opt/x2fa/.venv/bin/gunicorn wsgi:app -w 4 -b 127.0.0.1:5000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**nginx (mTLS + proxy):**
```nginx
server {
    listen 443 ssl;
    server_name 2fa.example.com;

    ssl_certificate     /etc/ssl/x2fa.crt;
    ssl_certificate_key /etc/ssl/x2fa.key;

    # Request client certificates from relying parties
    ssl_client_certificate /etc/ssl/trusted-cas.pem;
    ssl_verify_client      optional;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Client-Certificate $ssl_client_escaped_cert;
    }
}
```

**Initial setup (production):**
```bash
flask init-db
flask init-keys
flask add-ca production-ca /etc/ssl/ca.cert.pem
flask issue-client-cert myapp --ca production-ca --output /etc/x2fa/clients/
flask add-client myapp https://myapp.example.com/callback
```

---

## License

MIT
