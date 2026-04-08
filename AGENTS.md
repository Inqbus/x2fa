# X2FA Agent Guidelines

## Project Overview
X2FA is a FIDO2 microservice with OIDC provider that handles two-factor authentication. It supports WebAuthn/FIDO2, TOTP, and backup codes.

## Key Commands
- Run tests: `uv run pytest tests/ -v`
- Run single test: `uv run pytest tests/test_filename.py::test_name -v`
- Start development server: `uv run flask run`
- Database upgrade: `uv run flask db upgrade`
- Initialize keys: `uv run flask init-keys`
- Add client: `uv run flask add-client <client_id> <redirect_uri>`

## Environment Setup
- Requires Python 3.11+ and uv package manager
- Set `FLASK_APP=wsgi:app` for CLI commands
- Configure `.env` file with `X2FA_SECRET`, `X2FA_DOMAIN`, and `X2FA_ENV=development`
- For testing, ensure `X2FA_ORIGIN=http://localhost:5000` in development

## Testing Notes
- 107 tests currently passing
- Tests include E2E and unit tests
- Some tests are end-to-end with Playwright using Chromium browser
- Run specific test file with: `uv run pytest tests/test_file.py -v`

## Architecture
- Flask-based web application
- SQLAlchemy ORM for database (SQLite by default, supports PostgreSQL/MySQL)
- Redis required for rate limiting in production
- OIDC Authorization Code flow with PKCE S256
- FIDO2/WebAuthn support via py_webauthn
- TOTP support via pyotp
- Session-based state management (not JWT in URLs)
- ES256 ID tokens with public key verification