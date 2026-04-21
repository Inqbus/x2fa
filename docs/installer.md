# X2FA Installer

A Textual TUI wizard that takes a fresh X2FA installation to a running,
production-ready instance in a single session.

---

## Running the installer

**From a wheel (recommended for production):**

```bash
uv tool install 'x2fa[installer] @ x2fa-2.0.0-py3-none-any.whl'
x2fa-install
```

**From the source tree (development):**

```bash
uv run installer
```

**Optional flag:**

```
--config-root DIR   Override the base directory for all config and data files.
                    Default: ~  (config lands in ~/.config/x2fa/, data in ~/.local/share/x2fa/)
                    Useful for testing or running two instances on the same host.
```

---

## Screens

The installer is a linear wizard. Each screen shows `← Back` and `Continue →`
buttons for navigation. Session state is automatically saved to
`~/.local/share/x2fa/installer_session.json` so a partial run can be resumed.

### 1. Preflight (WelcomeScreen)

Runs a set of environment checks before any files are written.

| Check | Type | Action if it fails |
|---|---|---|
| Python ≥ 3.11 | **Blocking** | `uv python install 3.11` |
| uv package manager | **Blocking** | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `~/.config/x2fa` writable | **Blocking** | `mkdir -p ~/.config/x2fa && chmod u+rwx ~/.config/x2fa` |
| `~/.local/share/x2fa` writable | **Blocking** | `mkdir -p ~/.local/share/x2fa && chmod u+rwx ~/.local/share/x2fa` |
| `~/.config/systemd/user` writable | **Blocking** | `mkdir -p ~/.config/systemd/user && chmod u+rwx ~/.config/systemd/user` |
| Running as root | Warning | Create a dedicated user and re-run as that user |
| Port 5000 free | Warning | `lsof -ti:5000 \| xargs kill` |
| Redis reachable on localhost:6379 | Warning | Only needed for multiple Gunicorn workers |

**Blocking** checks hide the Continue button until resolved.
**Warning** checks allow continuation but may cause runtime problems.

Press **F1** for detailed guidance on each check.

### 2. Database (DatabaseScreen)

Choose the database backend:

| Option | Notes |
|---|---|
| **SQLite** (default) | Zero-config. Single writer. Good for most deployments. |
| **PostgreSQL** | Requires `psycopg2-binary`; install with `uv sync --extra postgres`. |
| **MySQL** | Requires `pymysql`; install with `uv sync --extra mysql`. |

For PostgreSQL and MySQL, a connection URI input is shown with a **Test connection**
button that verifies reachability before continuing.

### 3. Domain & Proxy (DomainScreen)

| Field | Description |
|---|---|
| Domain | The public hostname X2FA will be served from (e.g. `2fa.myapp.io`) |
| Reverse proxy | `caddy` / `nginx` / `traefik` / `other` — selects the config snippet shown in Summary |

The `ORIGIN` (`https://<domain>`) is derived automatically and written into
`x2fa_config.toml`.

### 4. Security (SecurityScreen)

Generates cryptographic material automatically:

| Value | Purpose |
|---|---|
| `SECRET_KEY` | Signs sessions, encrypts TOTP secrets, signs JWTs. **Changing it after install invalidates all sessions and encrypted secrets.** |
| `SECRET_SALT` | Anonymises IP addresses in the audit log. |

Rate limiter storage:

- **memory://** — single Gunicorn worker; no external dependency.
- **Redis URI** — required when running multiple workers. A connection test is run on blur.

### 5. Client Authentication (ClientScreen)

Registers the first OIDC relying-party client. Fields adapt based on the selected method.

| Method | Trust model | Installer generates | Production-suitable |
|---|---|---|---|
| `tls_client_auth` | CA-signed mTLS certificate | CA key + cert, client cert + key | **Yes** (recommended) |
| `private_key_jwt` | JWT signed by RP's own EC key, verified via JWKS | — | Yes |
| `self_signed_tls_client_auth` | SHA-256 fingerprint of a self-signed cert you provide | — | Acceptable |
| `client_secret_jwt` | HMAC-signed JWT | 64-char hex secret | With caution |
| `client_secret_post` | Secret in POST body | 64-char hex secret | No |
| `client_secret_basic` | HTTP Basic auth | 64-char hex secret | No |

For `client_secret_*` methods the plaintext secret is generated in the installer
process, passed to `flask add-client --secret`, and shown **once** on the Summary
screen. It is never written to the session file.

### 6. CA Setup (CASetupScreen)

Shown only for `tls_client_auth` and `private_key_jwt`.

- **Generate new CA** — creates a self-signed CA key + cert with configurable CN and
  validity period. Key is written to `~/.local/share/x2fa/ca_key.pem` (mode 0600).
- **Import existing CA** — provide the path to an existing CA cert PEM file.

### 7. Review (ReviewScreen)

A read-only summary of every collected value grouped by topic. Last chance to correct
mistakes before the irreversible execute step.

### 8. Execute (ExecuteScreen)

Runs all installation steps sequentially with live output:

| Step | Command | Idempotent? |
|---|---|---|
| Write configuration files | `config_writer.write_configs()` | Yes — overwrites |
| Write systemd user service | `config_writer.write_systemd_unit()` | Yes — overwrites |
| Initialize database | `flask init-db` → Alembic `upgrade head` | Yes — safe on existing DB |
| Generate signing keys | `flask init-keys` | Yes — skips if present |
| Generate CA certificate | `installer.ca.generate_ca()` | No — creates new files |
| Register CA in X2FA | `flask add-ca` | Yes — skips if already registered |
| Register OIDC client | `flask add-client` | Yes — updates if already registered |
| Issue client certificate | `installer.ca.issue_client_cert()` | No — creates new cert |
| Enable systemd service | `systemctl --user enable --now x2fa.service` | Yes |

A **Retry** button appears on step failure to re-run from that step.

The systemd activation step is non-blocking: if it fails (e.g. no D-Bus over SSH)
the installation is still considered successful and a hint is shown.

### 9. Summary (SummaryScreen)

Displays after a successful run:

- systemd unit path and enable commands
- Manual start command
- Generated file paths (CA key, CA cert, client cert, client key)
- **Client secret** (for `client_secret_*` methods) — highlighted with a
  "record this now" warning
- Reverse proxy config snippet for the chosen proxy type
- Next-steps checklist

A **Copy summary** button copies the full text to the clipboard (or opens an overlay
on systems without clipboard access).

A **Set up Demo RP →** button opens the optional Demo RP screen.

### 10. Demo RP Setup (DemoRPScreen) — optional

Registers the bundled demo relying party for end-to-end testing with support for **all six auth methods**:

1. **Preflight checks** — verifies port availability, X2FA reachability, and demo_rp directory writability
2. `flask add-ca demo-rp-ca <ca_cert>` (idempotent, only for PKI methods)
3. `flask add-client demo-rp http://localhost:<port>/callback --method <your-auth-method>`
4. Issue `demo-rp.cert.pem` + `demo-rp.key.pem` (only for PKI methods)
5. Write `demo_rp/demo_rp_settings.toml` with correct auth method

The installer automatically uses the same auth method as the main installation:
- For secret methods, appends the generated secret to the settings file
- For PKI methods, uses the CA key to issue the demo RP certificate
- For `self_signed_tls_client_auth`, prompts for the self-signed cert path

The file `demo_rp/demo_rp_settings.toml` contains example configurations for all six methods in comments.

Available for all auth methods (PKI and secret).

### 11. CA Manage (CAManageScreen) — main menu option

Available from the main menu (not part of the install flow). Lists registered CAs and
allows revoking them via `flask revoke-ca`.

---

## Architecture

```
installer/
├── __main__.py          # entry point; argparse; friendly error for missing [installer] extra
├── app.py               # InstallerApp (Textual); screen routing; session save/load
├── models.py            # InstallConfig dataclass; XDG paths; session persistence
├── runner.py            # thin wrappers around flask CLI (subprocess via sys.executable)
├── ca.py                # CA key+cert generation; client cert issuance (cryptography lib)
├── config_writer.py     # writes *.toml config files; writes systemd unit file
└── screens/
    ├── welcome.py       # preflight checks
    ├── database.py      # DB backend selection + connection test
    ├── domain.py        # domain + proxy type
    ├── security.py      # SECRET_KEY / SECRET_SALT generation; Redis toggle
    ├── client.py        # OIDC client fields; auth method selection
    ├── ca_setup.py      # CA generate / import
    ├── review.py        # read-only config summary before execute
    ├── execute.py       # step runner with live log; retry button
    ├── summary.py       # post-install summary; copy button; demo-rp launch
    ├── demo_rp.py       # optional demo RP registration
    └── ca_manage.py     # CA list + revoke (post-install)
```

**Key design decisions:**

- `runner.py` uses `sys.executable -m flask` (never `uv run flask`) so it always
  uses the same Python environment as the installer, whether that is a dev venv or a
  `uv tool install` environment.
- Auth method constants (`PKI_CA_METHODS`, `SECRET_METHODS`, individual method names)
  are defined once in `x2fa.constants` and imported by both the installer and the app.
- The client secret is generated in `execute.py` before the subprocess call and passed
  to `flask add-client --secret`. It is never parsed from command output.
- `InstallConfig` fields excluded from session persistence:
  `install_root`, `config_root`, `generated_files`, `install_error`, `client_secret`.

---

## Session persistence

The installer saves all user-entered fields to
`~/.local/share/x2fa/installer_session.json` whenever a screen is pushed or popped.
On the next run, the saved values pre-fill every screen. Sensitive fields and
transient results are excluded (see above).

To start fresh, delete the session file:

```bash
rm ~/.local/share/x2fa/installer_session.json
```

---

## What the installer does NOT do

- **Reverse proxy configuration** — generates a ready-to-paste config snippet;
  the operator pastes it and reloads the proxy.
- **Firewall rules** — out of scope.
- **Non-interactive / headless mode** — no `--answers` flag yet; planned.
- **Multi-instance management** — use `--config-root` to separate instances;
  no shared management UI.
