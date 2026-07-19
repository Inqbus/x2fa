# X2FA — CLI Reference

All administration commands use the Flask CLI with the `wsgi_cli` entry point.

## Prerequisites

```bash
export FLASK_APP=x2fa.wsgi_cli:app
```

## Database Commands

### `flask init-db`

Creates all database tables on a fresh database. Uses Alembic internally.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask init-db
```

- Creates all tables via Alembic `upgrade head`
- Stamps the schema version if tables already exist (safe to re-run)
- **Does not drop existing data** — use with caution on production databases

### `flask db-upgrade`

Applies pending Alembic migrations. Safe for existing installations.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask db-upgrade
```

## Key Management

### `flask init-keys`

Generates an ES256 signing key pair and stores it in the database.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask init-keys
```

- Generates EC P-256 key pair
- Private key stored Fernet-encrypted
- Public key stored in PEM format
- Key is active by default, never expires

### `flask rotate-keys`

Creates a new signing key and activates it. The old key remains active until
explicitly deactivated or expired.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask rotate-keys
```

## OIDC Client Management

### `flask add-client`

Registers a new OIDC client (relying party).

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask add-client <client_id> <redirect_uri> [--method <method>]
```

| Parameter | Description |
|-----------|-------------|
| `client_id` | Unique client identifier |
| `redirect_uri` | Valid redirect URI (newline-separated for multiple) |
| `--method` | Authentication method (default: `tls_client_auth`) |

Supported methods:

| Method | Description | Requires CA |
|--------|-------------|-------------|
| `tls_client_auth` | mTLS with trusted CA | Yes |
| `private_key_jwt` | JWT client assertions with JWKS URI | Yes |
| `self_signed_tls_client_auth` | Self-signed client cert | No (but must be imported) |
| `client_secret_jwt` | JWT client assertions with shared secret | No |
| `client_secret_post` | Shared secret in POST body | No |
| `client_secret_basic` | Shared secret in Authorization header | No |

### `flask list-clients`

Lists all registered OIDC clients.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask list-clients
```

### `flask delete-client`

Removes an OIDC client.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask delete-client <client_id>
```

## CA Management

### `flask add-ca`

Adds a trusted Certificate Authority.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask add-ca <name> <cert_path>
```

| Parameter | Description |
|-----------|-------------|
| `name` | Unique CA name (used as identifier) |
| `cert_path` | Path to PEM-encoded CA certificate |

**Security:** The path is resolved and validated to prevent path traversal attacks.
Only regular files are accepted.

### `flask list-cas`

Lists all trusted CAs.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask list-cas
```

### `flask revoke-ca`

Deactivates a trusted CA.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask revoke-ca <name>
```

### `flask issue-client-cert`

Issues a client certificate signed by a trusted CA.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask issue-client-cert <client_id> --ca <name>
```

- Generates EC P-256 key pair
- Creates CSR with CN = client_id
- Signs with the specified CA
- Writes key and cert files to `~/.local/share/x2fa/`

## Security

### `flask generate-secret`

Generates a cryptographically secure random secret for client_secret_* methods.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask generate-secret
```

Output: 64-character hex string.

## Maintenance

### `flask cleanup-codes`

Removes expired authorization codes and consumed challenges.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask cleanup-codes
```

- Removes `AuthorizationCode` rows where `expires_at < now`
- Removes `Challenge` rows where `expires_at < now` or `used = True` and older than 1 hour

### `flask install-systemd`

Installs a systemd user service unit for automatic startup.

```bash
FLASK_APP=x2fa.wsgi_cli:app uv run flask install-systemd
```

Creates `~/.config/systemd/user/x2fa.service` and enables it:

```bash
systemctl --user enable --now x2fa.service
```

## Path Resolution

All file paths are resolved through `x2fa.paths`:

| Function | Default Path |
|----------|-------------|
| `get_home()` | `~` (or `$X2FA_HOME`) |
| `config_dir()` | `$X2FA_HOME/.config/x2fa/` |
| `data_dir()` | `$X2FA_HOME/.local/share/x2fa/` |
| `db_path()` | `$X2FA_HOME/.local/share/x2fa/db.sqlite` |
| `ca_key_path()` | `$X2FA_HOME/.local/share/x2fa/ca_key.pem` |
| `ca_cert_path()` | `$X2FA_HOME/.local/share/x2fa/ca_cert.pem` |

Override all paths with `X2FA_HOME`:

```bash
X2FA_HOME=/tmp/x2fa-test FLASK_APP=x2fa.wsgi_cli:app uv run flask init-db
```

## Security Features

### Path Traversal Protection

The `_resolve_file()` helper in `cli.py` validates all file paths:

```python
def _resolve_file(path_str: str, label: str = "path") -> Path:
    p = Path(path_str).expanduser().resolve()
    if not p.is_file():
        raise click.ClickException(f"{label}: file does not exist: {path_str}")
    return p
```

- Resolves symlinks and relative paths
- Only accepts regular files (not directories or symlinks to arbitrary locations)
- Validates parent directory is writable

### Nonce Protection

AuthorizationCodes werden nach Token-Exchange nicht physisch gelöscht (nur `used=True` markiert).
`cleanup-codes` entfernt sie erst nach 1h. Das ermöglicht dem RP, das ID-Token
(60s Expiry) auch noch nach dem Token-Exchange zu verarbeiten. Der echte Replay-Schutz
kommt daher, dass der AuthorizationCode selbst nicht erneut getauscht werden kann.

### IP Hashing

Audit logs store `SHA256(ip + X2FA_SECRET)` instead of plaintext IP addresses
for GDPR compliance. The secret is loaded from the security config.