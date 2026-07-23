# X2FA — Getting Started

X2FA is a FIDO2 / TOTP microservice with an integrated OIDC provider. It provides
two-factor authentication (2FA) for relying parties (RPs) and supports six client
authentication methods — from PKI-based (mTLS, private_key_jwt) to shared-secret approaches.

## Quick Overview

| Component | Description |
|-----------|-------------|
| **Web framework** | Flask (factory pattern via `create_app()`) |
| **ORM** | SQLAlchemy (SQLite default, PostgreSQL/MySQL via extras) |
| **Migrations** | None — `init-db` creates all tables (no Alembic) |
| **Rate limiting** | Flask-Limiter (Redis required for multi-worker) |
| **OIDC** | Authlib server (Authorization Code + PKCE S256) |
| **FIDO2** | py_webauthn 3.x (WebAuthn / FIDO2) |
| **TOTP** | pyotp |
| **I18n** | Flask-Babel (German default) |
| **Installer** | Textual TUI (`x2fa-install` / `uv run --extra installer`) |

## Prerequisites

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) package manager
- Non-root user (X2FA must never run as root)

## Installation

```bash
# Clone and enter the project
git clone https://.../x2fa.git && cd x2fa

# Create virtual environment with uv
uv venv
source .venv/bin/activate

# Install dependencies (including installer extras)
uv pip install -e ".[installer]"

# Initialize the database
FLASK_APP=x2fa.wsgi_cli:app uv run flask init-db

# Generate signing keys
FLASK_APP=x2fa.wsgi_cli:app uv run flask init-keys

# Start the development server
FLASK_APP=x2fa.wsgi:app uv run flask run
```

## Configuration

X2FA uses XDG-compliant TOML config files. The default root is `~/.config/x2fa/`.

| File | Purpose |
|------|---------|
| `x2fa_config.toml` | Domain, database URI, OIDC settings |
| `security_config.toml` | Secret key, session cookie settings |
| `db_config.toml` | Database-specific settings |
| `ratelimit_config.toml` | Rate limiting configuration |
| `babel_config.toml` | i18n / locale settings |

Override the config root with `X2FA_HOME`:

```bash
X2FA_HOME=/tmp/x2fa-test FLASK_APP=x2fa.wsgi:app uv run flask run
```

## Key Directories

| Path | Contents |
|------|----------|
| `~/.config/x2fa/` | TOML config files |
| `~/.local/share/x2fa/` | CA key/cert, database, client certs |
| `~/.config/systemd/user/` | systemd user service unit |

## Running in Production

```bash
# Start via systemd (recommended)
FLASK_APP=x2fa.wsgi:app uv run flask install-systemd
systemctl --user enable --now x2fa.service

# Or start directly with gunicorn
gunicorn --bind 127.0.0.1:5000 --workers 2 x2fa.wsgi:app
```

A reverse proxy (nginx, Caddy) must be configured to forward requests to `127.0.0.1:5000`.

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run a single test
uv run pytest tests/test_file.py::test_name -v

# Run only unit tests (no DB, no I/O)
uv run pytest tests/ -m unit -v
```

## Quick Reference

| Task | Command |
|------|---------|
| Initialize database | `FLASK_APP=x2fa.wsgi_cli:app uv run flask init-db` |
| Create signing keys | `FLASK_APP=x2fa.wsgi_cli:app uv run flask init-keys` |
| Register OIDC client | `FLASK_APP=x2fa.wsgi_cli:app uv run flask add-client <id> <uri> [--method <method>]` |
| Add CA | `FLASK_APP=x2fa.wsgi_cli:app uv run flask add-ca <name> <cert>` |
| Issue client cert | `FLASK_APP=x2fa.wsgi_cli:app uv run flask issue-client-cert <id> --ca <name>` |
| Rotate signing keys | `FLASK_APP=x2fa.wsgi_cli:app uv run flask rotate-keys` |
| Cleanup | `FLASK_APP=x2fa.wsgi_cli:app uv run flask cleanup-codes` |

## Documentation Structure

| File | Content |
|------|---------|
| **getting-started.md** | This file — installation, quickstart, configuration |
| [architecture.md](architecture.md) | System design, request flows, data models, session management |
| [cli-reference.md](cli-reference.md) | All Flask CLI commands, path resolution |
| [oidc-auth.md](oidc-auth.md) | OIDC discovery, 6 auth methods, authorization/token endpoint, 2FA flows |
| [installer.md](installer.md) | Textual TUI, screens, InstallConfig, preflight checks |
| [security.md](security.md) | Cryptography, audit logging, WebAuthn security, PKCE, rate limiting |