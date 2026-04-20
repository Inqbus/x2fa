# X2FA Installation Guide

## Requirements

| Requirement | Notes |
|---|---|
| Python ≥ 3.11 | Check with `python3 --version` |
| [uv](https://docs.astral.sh/uv/) | Package and project manager |
| A reverse proxy | Caddy, nginx, or traefik (handles TLS) |
| Redis *(optional)* | Required when running multiple Gunicorn workers |

X2FA does **not** need to be run as root. A dedicated system user (e.g. `x2fa`) is recommended.

---

## 1. Get the Code

```bash
git clone https://github.com/your-org/x2fa.git
cd x2fa
```

The installer expects to run from the repository root. All config files and the database are relative to this directory.

---

## 2. Run the Installer TUI

```bash
uv run --extra installer python -m installer
```

The installer is a terminal UI that walks through every configuration step and runs all
Flask CLI commands automatically. Press `F1` on any screen to open a contextual help
panel explaining every option. The screens are:

1. **Preflight checks** — verifies Python ≥ 3.11, uv, port 5000 availability, Redis
2. **Database** — SQLite (default), PostgreSQL, or MySQL
3. **Domain & Proxy** — your public domain and reverse proxy type
4. **Security** — auto-generates `SECRET_KEY` (64 hex chars) and `SECRET_SALT` (32 hex
   chars); optional Redis URI for rate limiting
5. **First OIDC Client** — client ID, redirect URI, and **authentication method** (see
   [Client Authentication Methods](#client-authentication-methods) below)
6. **Certificate Authority** *(PKI methods only)* — generate a new self-signed CA or
   import an existing one
7. **Review** — read-only summary of all collected settings; last chance to go back
8. **Execute** — writes config files, initialises the database and signing keys, registers
   the CA and client, issues the client certificate
9. **Summary** — start command, generated file paths, reverse proxy snippet, next-steps
   checklist

When the execute step completes, configuration files are written to `~/.config/x2fa/`
and data files (CA key, database) to `~/.local/share/x2fa/`. No environment variables
are required at runtime beyond `ENV_FOR_DYNACONF=production`.

### `--config-root` flag

```bash
uv run --extra installer python -m installer --config-root /opt/x2fa
```

Relocates **all** config and data paths under the given directory instead of the XDG
defaults:

| Default (XDG) | With `--config-root /opt/x2fa` |
|---|---|
| `~/.config/x2fa/x2fa_config.toml` | `/opt/x2fa/.config/x2fa/x2fa_config.toml` |
| `~/.local/share/x2fa/db.sqlite` | `/opt/x2fa/.local/share/x2fa/db.sqlite` |
| `~/.local/share/x2fa/ca_key.pem` | `/opt/x2fa/.local/share/x2fa/ca_key.pem` |

Useful for:
- Running X2FA as a dedicated system user (e.g. `--config-root /etc/x2fa`)
- **Multi-instance deployments** — two X2FA instances on the same host use different
  config roots:

  ```bash
  python -m installer --config-root /opt/x2fa-staging
  python -m installer --config-root /opt/x2fa-production
  ```

  Start each instance with the matching root:

  ```bash
  CONFIG_ROOT=/opt/x2fa-staging ENV_FOR_DYNACONF=production \
      uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5001

  CONFIG_ROOT=/opt/x2fa-production ENV_FOR_DYNACONF=production \
      uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5000
  ```

---

## 3. Client Authentication Methods

Choose one method per OIDC client when registering. The method determines what
credentials the relying-party application presents at the `/token` endpoint.

| Method | Trust model | CA required? | Shared secret? | Recommended |
|---|---|---|---|---|
| `tls_client_auth` | CA-signed mTLS certificate | Yes | No | **Yes** |
| `private_key_jwt` | JWT signed with client's EC key, verified via JWKS | Yes | No | Yes |
| `self_signed_tls_client_auth` | SHA-256 fingerprint of a self-signed cert | No | No | Acceptable |
| `client_secret_jwt` | HMAC-signed JWT (HS256) | No | Yes | With caution |
| `client_secret_post` | Secret in POST body | No | Yes | No |
| `client_secret_basic` | HTTP Basic authentication | No | Yes | No |

**For `tls_client_auth`:** The installer generates a CA key/cert pair and issues a
client certificate. Copy the `.cert.pem` and `.key.pem` files to the relying-party server.

**For `private_key_jwt`:** Provide a JWKS URI. The relying party generates its own EC key
pair and signs JWT assertions with it. X2FA fetches the public key from the JWKS endpoint.

**For `self_signed_tls_client_auth`:** Provide the path to the existing self-signed
certificate PEM. The installer pins its SHA-256 fingerprint. No CA is needed.

**For `client_secret_jwt`, `_post`, `_basic`:** The installer auto-generates a
64-character random secret and prints it **once** in the execution log. Record it
immediately — it is stored only as a Fernet-encrypted value and cannot be retrieved later.
Use `flask rotate-client-secret <client_id>` to issue a new secret.

---

## 4. Start X2FA

```bash
ENV_FOR_DYNACONF=production uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5000
```

For a systemd service, create `/etc/systemd/system/x2fa.service`:

```ini
[Unit]
Description=X2FA FIDO2/OIDC microservice
After=network.target

[Service]
User=x2fa
WorkingDirectory=/opt/x2fa
Environment=ENV_FOR_DYNACONF=production
ExecStart=uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5000 --workers 4
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now x2fa
```

When running multiple Gunicorn workers (`--workers > 1`), Redis is required for
distributed rate limiting. Enable it in the installer's Security screen or set
`RATELIMIT_STORAGE_URI` in `src/x2fa/config_files/ratelimit_config.toml`.

---

## 5. Reverse Proxy Configuration

X2FA must be behind a TLS-terminating reverse proxy. The proxy is responsible for:
- Serving HTTPS on port 443
- For `tls_client_auth` and `private_key_jwt` (x5c): forwarding the client certificate
  as the `X-Client-Certificate` header

### Caddy

```caddy
your.domain.com {
    reverse_proxy localhost:5000
}
```

For mTLS (`tls_client_auth`):

```caddy
your.domain.com {
    tls {
        client_auth {
            mode                 request
            trusted_ca_cert_file /etc/x2fa/ca_cert.pem
        }
    }
    header_up X-Client-Certificate {http.request.tls.client.certificate_pem_escaped}
    reverse_proxy localhost:5000
}
```

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name your.domain.com;

    ssl_certificate     /etc/letsencrypt/live/your.domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your.domain.com/privkey.pem;

    # Optional client-cert verification — required for tls_client_auth
    ssl_verify_client      optional;
    ssl_client_certificate /etc/x2fa/ca_cert.pem;
    ssl_verify_depth       2;

    location /token {
        ssl_verify_client on;
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host               $host;
        proxy_set_header X-Forwarded-Proto  $scheme;
        proxy_set_header X-Client-Certificate $ssl_client_escaped_cert;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 6. Manual Installation (without the TUI)

If you prefer to configure X2FA by hand:

### 6.1 Write configuration files

Config files live in `~/.config/x2fa/` (or `<config-root>/.config/x2fa/` if
`--config-root` was used). Create the directory and write the following files:

**`~/.config/x2fa/x2fa_config.toml`**:

```toml
[production]
DOMAIN = "your.domain.com"
ORIGIN = "https://your.domain.com"
```

**`~/.config/x2fa/security_config.toml`**:

```toml
[production]
SECRET_KEY  = "<64 random hex chars>"
SECRET_SALT = "<32 random hex chars>"
SESSION_COOKIE_SECURE   = true
SESSION_COOKIE_HTTPONLY = true
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = 600
```

Generate safe values with:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"  # SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(16))"  # SECRET_SALT
```

**`~/.config/x2fa/db_config.toml`** (only needed if not using SQLite):

```toml
[production]
SQLALCHEMY_DATABASE_URI = "postgresql://user:pass@localhost/x2fa"
```

### 6.2 Initialise the database and signing keys

```bash
FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production uv run flask init-db
FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production uv run flask init-keys
```

**`flask init-db`** runs Alembic `upgrade head` to create all tables. Safe on a fresh
database. Also safe to re-run on an existing database — Alembic will apply only the
missing migrations without touching existing data.

**`flask db-upgrade`** is an alias that does the same as `init-db` but with a name that
makes its intent clear on existing installations: apply pending schema migrations without
resetting the database.

Use `init-db` for fresh installs and CI. Use `db-upgrade` when upgrading an existing
production installation.

### 6.3 Register a Certificate Authority

```bash
FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production uv run flask add-ca my-ca /etc/x2fa/ca_cert.pem
```

### 6.4 Register an OIDC client

```bash
# CA-signed mTLS
FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production uv run flask add-client \
    shop.example.com https://shop.example.com/auth/callback \
    --method tls_client_auth

# Self-signed cert (fingerprint-pinned)
FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production uv run flask add-client \
    shop.example.com https://shop.example.com/auth/callback \
    --method self_signed_tls_client_auth \
    --cert /path/to/client_self_signed.pem

# Shared secret (printed once — record it)
FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production uv run flask add-client \
    shop.example.com https://shop.example.com/auth/callback \
    --method client_secret_post
```

### 6.5 Issue a client certificate (tls_client_auth only)

```bash
FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production uv run flask issue-client-cert \
    shop.example.com --ca my-ca --output ./certs
```

---

## 7. Post-Install Operations

All management commands require `FLASK_APP=wsgi:app ENV_FOR_DYNACONF=production` (or set
these in your shell environment).

### Clients

```bash
flask list-clients                        # list all registered clients
flask revoke-client <client_id>           # deactivate a client
flask rotate-client-secret <client_id>   # rotate secret (client_secret_* methods)
flask update-client-cert <client_id> --cert <path>  # re-pin cert (self_signed_tls)
flask issue-client-cert <client_id> --ca <name>     # re-issue cert (tls_client_auth)
```

### Certificate Authorities

```bash
flask list-cas                    # list CAs with expiry warnings
flask add-ca <name> <cert_path>   # register a new CA
flask revoke-ca <name>            # deactivate a CA (audit trail preserved)
```

CA renewal (via the post-install TUI):

```bash
uv run --extra installer python -m installer
# → select "Manage CAs" from the main menu
```

### Maintenance

```bash
flask stats                       # credential and audit log counts
flask cleanup-codes               # remove authorization codes older than 1 hour
```

---

## 8. Database Support

The default database is SQLite, stored at the path configured in `db_config.toml`.
PostgreSQL and MySQL are supported via optional extras:

```bash
uv sync --extra postgres   # psycopg2-binary
uv sync --extra mysql      # pymysql
```

Set `SQLALCHEMY_DATABASE_URI` accordingly in `db_config.toml`.

For existing installations, apply schema changes with:

```bash
ENV_FOR_DYNACONF=production uv run flask db-upgrade
```

This runs Alembic `upgrade head` and applies only the pending migrations — it never
drops tables or discards data.

---

## 9. OIDC Discovery

The discovery document is available at:

```
https://your.domain.com/.well-known/openid-configuration
```

The JWKS endpoint (public signing key for ID token verification):

```
https://your.domain.com/.well-known/jwks.json
```
