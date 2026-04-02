# X2FA — FIDO2 Microservice with OIDC Provider

X2FA is a standalone two-factor authentication microservice that exposes a standard **OpenID Connect (OIDC) Authorization Code Flow** to existing applications. After registering as an OIDC client, a relying party simply redirects users to X2FA for 2FA verification and receives a signed ID token in return — no shared secrets in URLs, no custom JWT handling.

**Supported second factors:**
- **WebAuthn / FIDO2** — Passkeys (FaceID, TouchID, Windows Hello), YubiKey, Nitrokey, phone-as-key (hybrid), any FIDO2-compatible authenticator
- **TOTP** — Google Authenticator, Aegis, FreeOTP, Authy, and any RFC 6238-compatible app
- **Backup codes** — 10 single-use hex codes generated at setup time

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
     │   code, code_verifier         │                               │
     │◀── { id_token (ES256) } ─────│                               │
```

**Key design decisions:**
- **Session-based state** — OIDC parameters are stored in the Flask server session, not passed as JWT tokens in URLs. The browser never sees credentials.
- **PKCE S256 mandatory** — `plain` is explicitly rejected. No exceptions.
- **ES256 ID tokens** — asymmetric EC P-256 keys; relying parties verify signatures using the public JWKS endpoint without sharing any secret.
- **Stateless access tokens** — no token storage in the database; only authorization codes are persisted (for 60 seconds, nonce-protected for 1 hour).

### Directory Layout

```
x2fa/
├── app/
│   ├── __init__.py          # create_app() factory
│   ├── config.py            # Config / TestingConfig / ProductionConfig
│   ├── extensions.py        # db, migrate, limiter
│   ├── models.py            # SQLAlchemy models (2FA + OIDC)
│   ├── cli.py               # Flask CLI commands
│   ├── oidc/
│   │   ├── __init__.py      # AuthorizationServer instance
│   │   └── grants.py        # X2FAAuthorizationCodeGrant, X2FAOpenIDCode
│   ├── routes/
│   │   ├── __init__.py      # audit_log() helper, action/method constants
│   │   ├── auth.py          # OIDC endpoints + /done demo callback
│   │   ├── setup.py         # WebAuthn registration flow
│   │   ├── verify.py        # WebAuthn assertion flow
│   │   ├── totp.py          # TOTP setup & verification
│   │   └── backup.py        # Backup code verification
│   └── services/
│       └── crypto.py        # Fernet encryption + bcrypt backup-code hashing
├── templates/               # Jinja2 templates (no tokens in URLs)
├── migrations/              # Alembic migration scripts
├── webauthn_helpers.py      # py_webauthn 2.x wrapper
├── totp_helpers.py          # pyotp wrapper
├── wsgi.py                  # WSGI entry point (gunicorn / flask run)
└── pyproject.toml
```

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (package manager)
- A reverse proxy with TLS (Caddy, nginx, Traefik, Cloudflare Tunnel…)
- SQLite (default), PostgreSQL, or MySQL
- Redis (required in production for distributed rate limiting)

---

## Installation

```bash
git clone <repo>
cd x2fa

# Install dependencies
uv sync

# Optional: PostgreSQL support
uv sync --extra postgres
```

---

## Configuration

All configuration is done via environment variables. Copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

### Required Variables

| Variable | Description | Example |
|---|---|---|
| `X2FA_SECRET` | Master secret ≥ 32 chars (derive Fernet key + Flask session key) | `openssl rand -hex 32` |
| `X2FA_DOMAIN` | Public domain of this X2FA instance | `2fa.example.com` |

### Optional Variables

| Variable | Default | Description |
|---|---|---|
| `X2FA_ORIGIN` | `https://<X2FA_DOMAIN>` | Override WebAuthn origin (use `http://localhost:5000` for local dev) |
| `X2FA_ENV` | `production` | App environment: `production`, `development`, `testing` |
| `DATABASE_URL` | `sqlite:///x2fa.db` | SQLAlchemy database URI |
| `REDIS_URL` | — | Required in production for distributed rate limiting |
| `X2FA_HOST` | `127.0.0.1` | Bind host (for `wsgi.py` direct run) |
| `X2FA_PORT` | `5000` | Bind port |
| `FLASK_SECRET_KEY` | — | Alternative to `X2FA_SECRET` for Flask session signing |

### Environment Classes

| `X2FA_ENV` | Database | HTTPS required | Redis required |
|---|---|---|---|
| `production` | env var | Yes | Yes |
| `development` | `sqlite:///x2fa.db` | No | No |
| `testing` | in-memory SQLite | No | No |

---

## First-Time Setup

```bash
# 1. Set environment variables
export X2FA_SECRET=$(openssl rand -hex 32)
export X2FA_DOMAIN=2fa.example.com
export X2FA_ENV=development
export FLASK_APP=wsgi:app

# 2. Initialize database (development creates tables automatically;
#    for production run migrations)
flask db upgrade

# 3. Generate EC signing key for ID tokens
flask init-keys

# 4. Register your first OIDC client
flask add-client myapp https://myapp.example.com/callback

# 5. Start the server
flask run
# or with gunicorn:
gunicorn wsgi:app -w 4 -b 127.0.0.1:5000
```

---

## OIDC Integration Guide

### Step 1 — Register a Client

```bash
flask add-client <client_id> <redirect_uri> [--secret <secret>] [--scopes "openid x2fa:setup"]
```

Note the printed `client_id` and `client_secret`.

### Step 2 — Authorization Request

Redirect the user to X2FA with these parameters:

```
GET https://2fa.example.com/authorize
  ?client_id=myapp
  &redirect_uri=https://myapp.example.com/callback
  &response_type=code
  &scope=openid                   # or "openid x2fa:setup" for registration
  &state=<random_state>
  &nonce=<random_nonce>
  &login_hint=<user_id>           # your internal user identifier
  &code_challenge=<S256_hash>
  &code_challenge_method=S256
```

**`login_hint`** carries the user identifier that X2FA uses to look up existing 2FA credentials. It appears as `sub` in the ID token.

**`scope=openid x2fa:setup`** triggers the setup flow (credential registration) instead of verification.

**PKCE** is mandatory. Generate the code pair:
```python
import secrets, hashlib, base64
code_verifier  = secrets.token_urlsafe(43)
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b'=').decode()
```

### Step 3 — Handle the Callback

X2FA redirects to your `redirect_uri` with:
```
GET https://myapp.example.com/callback?code=<auth_code>&state=<state>
```

Verify `state` matches what you sent.

### Step 4 — Exchange Code for Tokens

```bash
POST https://2fa.example.com/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<auth_code>
&redirect_uri=https://myapp.example.com/callback
&client_id=myapp
&client_secret=<client_secret>
&code_verifier=<code_verifier>
```

Response:
```json
{
  "access_token": "…",
  "token_type": "Bearer",
  "expires_in": 864000,
  "scope": "openid",
  "id_token": "<ES256-signed JWT>"
}
```

### Step 5 — Verify the ID Token

The ID token is signed with ES256. Fetch the public key from the JWKS endpoint and verify:

```python
from authlib.jose import JsonWebKey, jwt

# Fetch once and cache
jwks = requests.get("https://2fa.example.com/.well-known/jwks.json").json()
key  = JsonWebKey.import_key_set(jwks)

claims = jwt.decode(id_token, key)
claims.validate()

assert claims["iss"] == "https://2fa.example.com"
assert claims["aud"] == "myapp"
assert claims["sub"] == expected_user_id
assert claims["nonce"] == nonce_you_sent  # replay protection
```

### ID Token Claims

| Claim | Type | Description |
|---|---|---|
| `sub` | string | User identifier (value of `login_hint`) |
| `iss` | string | `https://<X2FA_DOMAIN>` |
| `aud` | string | `client_id` |
| `exp` | int | Expiry (60 seconds after issuance) |
| `iat` | int | Issued-at timestamp |
| `auth_time` | int | Unix timestamp of 2FA completion |
| `nonce` | string | Echoed nonce for replay protection |

---

## API Reference

### `GET /.well-known/openid-configuration`

OIDC Discovery document. Returns server metadata including endpoint URLs, supported algorithms, and supported scopes.

### `GET /.well-known/jwks.json`

JSON Web Key Set containing the active EC public key(s) for ID token signature verification.

### `GET /authorize`

**OIDC Authorization Endpoint.**

**Query parameters:**

| Parameter | Required | Description |
|---|---|---|
| `client_id` | Yes | Registered client identifier |
| `redirect_uri` | Yes | Must match a registered redirect URI |
| `response_type` | Yes | Must be `code` |
| `scope` | Yes | Must include `openid`; add `x2fa:setup` for registration flow |
| `login_hint` | Yes | User identifier to authenticate |
| `code_challenge` | Yes | PKCE S256 challenge |
| `code_challenge_method` | Yes | Must be `S256` |
| `state` | Recommended | Opaque string echoed in redirect |
| `nonce` | Recommended | Random value for replay protection |

**Behavior:**
- First call: validates parameters, stores them in session, redirects to the 2FA UI (`/verify` or `/setup`).
- Second call (after successful 2FA): issues the authorization code and redirects to `redirect_uri`.

### `POST /token`

**OIDC Token Endpoint.** Exchanges an authorization code for tokens.

Supported client authentication methods: `client_secret_post`, `client_secret_basic`.

### `GET /setup`

Displays the 2FA method selection screen (WebAuthn vs TOTP). Requires an active OIDC session.

### `GET /setup/webauthn`

Renders the WebAuthn credential registration UI.

### `POST /setup/complete`

Processes the WebAuthn registration response (JSON body from the browser). On success returns `{"redirect_url": "/setup/done"}` and generates 10 backup codes.

Rate limit: 5 per minute.

### `GET /setup/done`

Displays the one-time backup code screen. The codes are removed from the session on display.

### `GET /verify`

Renders the WebAuthn assertion UI. Falls back to `/totp/verify` if the user has no registered WebAuthn credentials.

### `POST /verify/complete`

Processes the WebAuthn assertion response. On success sets `session['2fa_verified'] = True` and returns `{"redirect_url": "/authorize?…"}`.

Rate limit: 10 per minute, 30 per hour.

### `GET /totp/setup` / `POST /totp/setup/verify`

TOTP provisioning flow. `GET` generates a new secret and QR code; `POST` verifies the first code to confirm setup.

Rate limit: 5 per minute, 20 per hour.

### `GET /totp/verify` / `POST /totp/verify`

TOTP verification. Includes replay protection (the same 30-second window cannot be used twice).

Rate limit: 5 per minute, 20 per hour.

### `GET /backup/verify` / `POST /backup/verify`

Backup code verification. Rate limit: 3 per minute per IP (in-memory sliding window).

### `GET /done`

Demo callback endpoint for local testing. Displays the received authorization code and state. **Do not use in production.**

---

## CLI Reference

All commands require `FLASK_APP=wsgi:app` and the environment variables to be set.

```bash
export FLASK_APP=wsgi:app
export X2FA_SECRET=...
export X2FA_DOMAIN=...
export X2FA_ENV=development
```

### `flask init-keys`

Generates a new EC P-256 signing key pair for ID token signing (ES256). The private key is encrypted with Fernet and stored in the database. Deactivates all previously active keys.

```bash
flask init-keys
# Signing key generated: kid=e44bbe26ab12dfce
```

Run this once after the first `flask db upgrade`, and whenever you rotate keys.

### `flask add-client <client_id> <redirect_uri>`

Registers a new OIDC client.

```bash
flask add-client myapp https://myapp.example.com/callback \
  --secret mysecret \
  --scopes "openid x2fa:setup"
```

Options:
- `--secret` — client secret (auto-generated if omitted)
- `--scopes` — allowed scopes, default: `openid x2fa:setup`

### `flask list-clients`

Lists all registered OIDC clients and their status.

### `flask revoke-client <client_id>`

Deactivates an OIDC client (sets `active=False`). Existing tokens remain valid until expiry.

### `flask stats`

Displays audit log statistics grouped by action and method, plus current credential/TOTP/backup-code counts.

### `flask cleanup-codes`

Deletes authorization codes older than 1 hour from the database. Safe to run as a cron job — codes younger than 1 hour are retained for nonce replay protection even after they have been used.

```bash
# Example cron: every 2 hours
0 */2 * * * cd /opt/x2fa && flask cleanup-codes
```

### `flask db upgrade`

Runs pending Alembic database migrations. Always run this after updating X2FA.

### `flask db migrate -m "description"`

Auto-generates a new migration from model changes (development use).

---

## Development & Testing

### Run Locally

```bash
cp .env.example .env
# edit .env: set X2FA_SECRET, X2FA_DOMAIN=localhost, X2FA_ORIGIN=http://localhost:5000

export FLASK_APP=wsgi:app
export X2FA_ENV=development

uv run flask db upgrade
uv run flask init-keys
uv run flask add-client testapp http://localhost:8080/callback --secret testsecret
uv run flask run --port 5000
```

### Generate Test Tokens (Legacy)

The `gen_token.py` script generates setup/verify URLs for the old token-based flow (Bottle). It is kept for reference only and does not work with the new OIDC flow.

For the new flow, use the `add-client` CLI command and construct an `/authorize` URL manually or with your RP's OAuth2 library.

### Running Tests

```bash
uv run pytest tests/ -v
```

> **Note:** The existing test suite was written for the Bottle-based implementation. Tests for the Flask/OIDC rewrite are forthcoming.

---

## Security Considerations

### PKCE S256 Enforcement

`plain` code challenge method is explicitly rejected. `code_challenge_method=S256` is mandatory and cannot be omitted. This prevents PKCE downgrade attacks.

### Nonce Replay Protection

Nonces are stored in the `authorization_codes` table. The `cleanup-codes` command only deletes codes older than **1 hour**, even if they have been used. This ensures that nonces from recently-issued ID tokens (60-second expiry) cannot be replayed.

### Rate Limiting

| Endpoint | Limit |
|---|---|
| `/totp/setup/verify` | 5/min, 20/hour |
| `/totp/verify` | 5/min, 20/hour |
| `/verify/complete` | 10/min, 30/hour |
| `/backup/verify` | 3/min per IP (in-memory) |
| `/authorize` | 10/min, 100/hour |
| `/token` | 20/min |

In production, use Redis (`REDIS_URL`) for distributed rate limiting across multiple workers. The `moving-window` strategy is used (not `fixed-window`) to prevent burst attacks at window boundaries.

### IP Anonymization

Client IP addresses are never stored in plaintext. The audit log stores `SHA256(ip + X2FA_SECRET)`, which is GDPR-compliant (pseudonymous) and allows rate-limiting by IP without retaining the raw address.

### Signing Key Rotation

The `flask init-keys` command generates a new key and deactivates the old one. The old public key remains in the JWKS endpoint until manually deleted, allowing relying parties to verify tokens issued before the rotation. Rotate keys periodically (e.g., every 90 days) by running `flask init-keys` and then updating the JWKS cache on all relying parties.

### Session Security

Flask sessions are signed with `X2FA_SECRET` and configured with:
- `SESSION_COOKIE_SECURE=True` (HTTPS only)
- `SESSION_COOKIE_HTTPONLY=True` (no JavaScript access)
- `SESSION_COOKIE_SAMESITE=Lax` (CSRF protection)
- `PERMANENT_SESSION_LIFETIME=10 minutes` (short-lived OIDC flow sessions)

### Content Security Policy

Every response includes a per-request CSP nonce. The `script-src` directive only allows scripts with the matching nonce, preventing XSS from inline script injection.

---

## Production Deployment

### Example: gunicorn + Caddy

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

**`Caddyfile`:**
```
2fa.example.com {
    reverse_proxy 127.0.0.1:5000
}
```

**`.env` (production):**
```bash
X2FA_SECRET=<openssl rand -hex 32>
X2FA_DOMAIN=2fa.example.com
X2FA_ENV=production
DATABASE_URL=postgresql://x2fa:password@localhost/x2fa
REDIS_URL=redis://localhost:6379/0
```

### Database Migration

```bash
flask db upgrade
flask init-keys
flask add-client <client_id> <redirect_uri>
```

### Multi-Worker Considerations

- **Rate limiting** requires Redis (`REDIS_URL`) when running multiple workers. Without Redis, each worker maintains an independent rate-limit counter.
- **Signing keys** are stored in the database and shared across all workers automatically.
- **Flask sessions** are server-side signed cookies; no sticky sessions are required.

---

## License

MIT
