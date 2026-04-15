# X2FA Agent Guidelines

## Project Overview
X2FA is a FIDO2 microservice with OIDC provider that handles two-factor authentication. It supports WebAuthn/FIDO2, TOTP, and backup codes. Client authentication uses X.509/mTLS and `private_key_jwt` — no shared secrets.

## Key Commands
- Run tests: `uv run pytest tests/ -v` (29 unit tests)
- Run single test: `uv run pytest tests/test_file.py::test_name -v`
- Start development server: `FLASK_APP=wsgi:app uv run flask run`
- Initialize database: `FLASK_APP=wsgi:app uv run flask init-db`
- Initialize keys: `FLASK_APP=wsgi:app uv run flask init-keys`
- Add client: `FLASK_APP=wsgi:app uv run flask add-client <client_id> <redirect_uri> [--method tls_client_auth|private_key_jwt]`
- Add CA: `FLASK_APP=wsgi:app uv run flask add-ca <name> <cert_path>`
- List CAs: `FLASK_APP=wsgi:app uv run flask list-cas`
- Revoke CA: `FLASK_APP=wsgi:app uv run flask revoke-ca <name>`
- Issue client cert: `FLASK_APP=wsgi:app uv run flask issue-client-cert <client_id> --ca <name>`
- Run demo RP: `cd demo_rp && uv run python app.py`

## Environment Setup
- Requires Python 3.11+ and uv package manager
- **Required env vars**: `X2FA_SECRET` (≥32 chars), `X2FA_DOMAIN`
- Optional: `X2FA_DATABASE_URL`, `X2FA_ORIGIN`, `X2FA_HOST`, `X2FA_PORT`, `X2FA_ENV`
- For testing: `X2FA_ORIGIN=http://localhost:5000` if running locally without HTTPS
- Config is loaded via **Dynaconf** from `src/x2fa/config_files/*.toml` and environment variables (prefix `X2FA_`)

## Testing Notes
- **29 unit tests** (all passing)
- Test structure:
  - `tests/test_*.py` — unit tests (pytest fixtures in `tests/conftest.py`)
  - `old_tests/e2e/test_*.py` — archived E2E tests (Playwright/Chromium, not yet updated for PKI auth)
- Demo RP (`demo_rp/app.py`) simulates an OIDC relying party for manual testing

## Architecture
- Flask-based web application with factory pattern (`create_app()` in `src/x2fa/app.py`)
- SQLAlchemy ORM for database (SQLite default, supports PostgreSQL/MySQL via extras)
- Redis required for distributed rate limiting in production
- OIDC Authorization Code flow with PKCE S256 (mandatory, `plain` rejected)
- FIDO2/WebAuthn support via py_webauthn 2.x (`src/x2fa/helpers/webauthn_helpers.py`)
- TOTP support via pyotp (`src/x2fa/helpers/totp_helpers.py`)
- Session-based state management (OIDC params not in URLs)
- ES256 ID tokens with public key verification (JWKS endpoint at `/.well-known/jwks.json`)

## Directory Structure
```
x2fa/
├── src/x2fa/
│   ├── app.py              # create_app() factory
│   ├── config.py           # Dynaconf configuration (cfg object)
│   ├── config_files/       # *.toml config files (x2fa_config, ratelimit, security, etc.)
│   ├── model/              # SQLAlchemy models (Credential, TOTPSecret, BackupCode, OIDCClient, TrustedCA, …)
│   ├── constants.py        # Sentinels (NEVER_USED), action/method strings
│   ├── cli.py              # Flask CLI commands
│   ├── wsgi.py             # WSGI entry point (loads .env, creates app)
│   ├── routes/             # Blueprints: auth, setup, verify, totp, backup
│   ├── oidc/               # Authlib OIDC server configuration
│   ├── services/           # Business logic (crypto, etc.)
│   ├── helpers/            # py_webauthn/pyotp wrappers
│   ├── init_app/           # Extension initialization (db, limiter, babel, security)
│   └── templates/          # Jinja2 templates
├── tests/
│   ├── conftest.py         # Unit test fixtures
│   └── test_*.py           # Unit tests
├── old_tests/              # Archived tests (pre-PKI, not yet updated)
├── demo_rp/                # Demo relying party for manual testing
└── .env                    # Local environment (git-ignored)
```

## Important Constraints
- **PKCE S256 enforced**: Code challenge method must be `S256`; `plain` is rejected
- **Nonces stored for 1 hour**: Even after use, to prevent replay of recently-issued ID tokens (60s expiry)
- **IP addresses never stored**: Audit log contains `SHA256(ip + X2FA_SECRET)` for GDPR compliance
- **Environment-specific config**: Dynaconf loads `[production]`, `[test]`, `[e2e]` sections from TOML files
- **Database sentinels**: `NEVER_USED` (1970-01-01) and `NEVER_EXPIRES` (9999-12-31) are timezone-naive
- **Babel i18n**: `ui_locales` OIDC parameter controls UI language (German default)

## Schema & Maintenance CLI
- Initialize schema: `uv run flask init-db` (creates all tables; no Alembic migrations)
- Cleanup old codes: `uv run flask cleanup-codes` (keep codes <1 hour for nonce protection)

## Reading files
- CRITICAL: When reading files, always read the COMPLETE file content, 
- never request partial snippets. Use the Read tool with full file access.
- Do not use "sed" to edit files. Always show diffs.
