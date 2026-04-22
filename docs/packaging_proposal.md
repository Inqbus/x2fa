# X2FA — Packaging and Distribution

**Status:** Proposal  
**Date:** 2026-04-22

> **ARCHIVED DOCUMENT** - Some snippets reference old Dynaconf patterns.
> The current system uses plain TOML files.

---

## 1. Summary

Four distribution channels in recommended implementation order:

| Channel | Audience | Install command | Self-contained? |
|---|---|---|---|
| **PyPI** | Python operators, developers | `pip install x2fa` | No |
| **Debian package** | Debian/Ubuntu server admins | `apt install x2fa` | Yes (vendored venv) |
| **AppImage** | Any Linux, no package manager | `./x2fa.AppImage` | Yes (bundled Python) |
| **OCI image** | Container / Kubernetes | `docker run ghcr.io/…/x2fa` | Yes |

Start with PyPI — it is the cheapest to implement and unblocks the others, since both
the Debian package and the AppImage build from the published wheel.

---

## 2. Technical Debt That Must Be Resolved First

These are not cosmetic issues. Each one is a blocker for at least one packaging channel.

### 2.1 Config path handled via `X2FA_CONFIG_DIR` *(resolved)*

Config is now loaded via `ConfigPool` from XDG locations: `~/.config/x2fa/` (non-root only). Environment variable `X2FA_CONFIG_DIR` can override the location for containers/CI/testing.

### 2.2 .env file handling removed *(resolved)*

`.env` file loading was removed from `wsgi.py`. Configuration is now managed exclusively via TOML files and environment variables with the `X2FA_` prefix.

### 2.3 No database migration system  *(blocks stable upgrades on all channels)*

`flask init-db` calls `db.reset_schema()` which executes `DROP ALL` + `CREATE ALL`.
It is destructive by design and must never run automatically on upgrade.

Without Alembic (or equivalent), there is no safe way to add columns or tables
across versions. This is already visible: the two new columns added for extended auth
methods (`client_cert_fingerprint`, `client_secret_encrypted`) require a manual
`ALTER TABLE` on existing installations (documented in `INSTALL.md §8`).

**Fix:** Add Alembic to the project.

```toml
# pyproject.toml — add to dependencies
"alembic>=1.13.0",
"flask-migrate>=4.0.0",   # thin Flask wrapper around Alembic
```

```python
# src/x2fa/app.py
from flask_migrate import Migrate

def create_app() -> Flask:
    app = Flask(...)
    ...
    migrate = Migrate(app, db.engine)   # enables `flask db` commands
    return app
```

New workflow:
- `flask db upgrade` — safe, incremental, idempotent; runs on every start/upgrade
- `flask init-db` — remains available, clearly marked "first install only / destroys data"

Until Alembic is added, operators upgrading from any previous version must run the
ALTER TABLE statements from `INSTALL.md §8` by hand. This is acceptable for an
internal/alpha release but must not ship in a public stable release.

### 2.4 Template folder is discoverable via `importlib.resources` *(resolved)*

Flask's `Flask(__name__, template_folder=...)` pattern works correctly when templates are declared as package data in `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"x2fa" = ["templates/**/*.html"]
```

When installed, Flask discovers templates via the package's `__file__`. Multi-stage Docker builds copy templates into the wheel, so no source tree is required at runtime.

### 2.5 Installer writes to XDG config directory *(resolved)*

The installer in `installer/config_writer.py` now writes config files to `~/.config/x2fa/` (non-root only) instead of the source tree. Config files are read from the XDG location via `ConfigPool`.

---

## 3. Channel A — PyPI

### 3.1 Requirements

| Tool | Version | Purpose |
|---|---|---|
| `uv` or `build` | latest | Build wheel and sdist |
| `twine` | ≥ 5.0 | Upload to PyPI (or use trusted publishing) |
| GitHub Actions | — | Release automation |

### 3.2 Changes to `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[tool.setuptools.packages.find]
where = ["src", "."]

[tool.setuptools.package-data]
"x2fa" = [
    "config_files/*.toml",
    "templates/**/*.html",
    "translations/**/*.mo",
]
"installer" = ["**/*.py"]

[project.scripts]
x2fa-server  = "x2fa.wsgi:main"
x2fa-install = "installer.__main__:main"
```

Add `main()` to `wsgi.py`:

```python
def main():
    """Entry point for the x2fa-server console script."""
    import sys
    from gunicorn.app.wsgiapp import WSGIApplication

    sys.argv = ["gunicorn", "x2fa.wsgi:app"] + sys.argv[1:]
    WSGIApplication("%(prog)s [OPTIONS]").run()
```

### 3.3 Release workflow (`.github/workflows/release.yml`)

```yaml
name: Release

on:
  push:
    tags: ["v*.*.*"]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv build
      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish-pypi:
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write       # required for trusted publishing
    steps:
      - uses: actions/download-artifact@v4
        with: { name: dist, path: dist/ }
      - uses: pypa/gh-action-pypi-publish@release/v1

  publish-ghcr:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      packages: write
      id-token: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.ref_name }}
      - uses: sigstore/cosign-installer@v3
      - run: cosign sign --yes ghcr.io/${{ github.repository }}:${{ github.ref_name }}
```

### 3.4 What the user gets

```bash
pip install x2fa                  # core service + gunicorn
pip install "x2fa[postgres]"      # + psycopg2-binary
pip install "x2fa[mysql]"         # + pymysql
pip install "x2fa[installer]"     # + Textual TUI installer

x2fa-install                      # run the TUI installer
X2FA_CONFIG_DIR=/etc/x2fa \
   \
  x2fa-server --workers 4         # start Gunicorn
```

### 3.5 Upgrade

```bash
pip install --upgrade x2fa
flask db upgrade                  # once Alembic is added; no-op today
```

User config in `X2FA_CONFIG_DIR` is never touched by pip.

---

## 4. Channel B — Debian Package

### 4.1 Requirements

| Tool | Version | Notes |
|---|---|---|
| `dh-virtualenv` | ≥ 1.2.2 | Bundles a virtualenv into the `.deb` |
| `debhelper` | ≥ 13 | Build toolchain |
| `python3` | ≥ 3.11 | On the build machine |
| `dpkg-dev` | — | `dpkg-buildpackage` |
| `lintian` | — | Package quality checks |

Build on Debian 12 (Bookworm) or Ubuntu 22.04 LTS for maximum compatibility.
`dh-virtualenv` is available in Debian's `contrib` repository.

### 4.2 Package layout

```
/opt/x2fa/                        ← relocatable virtualenv (root:root, 755)
  bin/flask
  bin/gunicorn
  bin/x2fa-install
  bin/x2fa-server
  lib/python3.11/site-packages/x2fa/
  lib/python3.11/site-packages/installer/

/etc/x2fa/                        ← operator config (x2fa:x2fa, 750) — dpkg conffile
  x2fa_config.toml
  db_config.toml
  security_config.toml
  ratelimit_config.toml
  babel_config.toml

/var/lib/x2fa/                    ← database, CA keys (x2fa:x2fa, 700)
/var/log/x2fa/                    ← log files (x2fa:adm, 750)

/lib/systemd/system/x2fa.service
/usr/bin/x2fa-install             ← symlink → /opt/x2fa/bin/x2fa-install
/usr/bin/x2fa-server              ← symlink → /opt/x2fa/bin/x2fa-server
```

### 4.3 `debian/control`

```
Source: x2fa
Section: net
Priority: optional
Maintainer: X2FA Maintainers <maintainers@example.com>
Build-Depends: debhelper-compat (= 13),
               dh-virtualenv (>= 1.2.2),
               python3 (>= 3.11),
               python3-pip,
               python3-venv
Standards-Version: 4.6.2

Package: x2fa
Architecture: any
Depends: ${misc:Depends},
         python3 (>= 3.11),
         adduser,
         libffi8,
         libssl3
Recommends: redis
Description: FIDO2/TOTP microservice with OIDC provider
 X2FA is a Flask-based two-factor authentication service supporting
 WebAuthn/FIDO2, TOTP, and backup codes. Client authentication uses
 X.509/mTLS or private_key_jwt — no shared secrets by default.
```

### 4.4 `debian/rules`

```makefile
#!/usr/bin/make -f
%:
	dh $@ --with python-virtualenv

override_dh_virtualenv:
	dh_virtualenv \
	    --python /usr/bin/python3 \
	    --install-suffix x2fa \
	    --builtin-venv \
	    --upgrade-pip \
	    --extra-pip-arg "--no-cache-dir"
```

### 4.5 `debian/x2fa.service`

```ini
[Unit]
Description=X2FA FIDO2/OIDC microservice
Documentation=https://github.com/your-org/x2fa
After=network.target redis.service
Wants=redis.service

[Service]
Type=notify
User=x2fa
Group=x2fa
WorkingDirectory=/var/lib/x2fa
Environment=
Environment=X2FA_CONFIG_DIR=/etc/x2fa
ExecStart=/opt/x2fa/bin/x2fa-server \
    --bind 127.0.0.1:5000 \
    --workers 4 \
    --worker-class gthread \
    --threads 2 \
    --access-logfile /var/log/x2fa/access.log \
    --error-logfile  /var/log/x2fa/error.log
ExecReload=/bin/kill -s HUP $MAINPID
Restart=on-failure
RestartSec=5
PrivateTmp=true
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/x2fa /var/log/x2fa /etc/x2fa

[Install]
WantedBy=multi-user.target
```

### 4.6 `debian/postinst`

```bash
#!/bin/bash
set -e

CONFIG_DIR=/etc/x2fa
DATA_DIR=/var/lib/x2fa
LOG_DIR=/var/log/x2fa
VENV=/opt/x2fa
FLASK="$VENV/bin/flask --app x2fa.wsgi"

case "$1" in
  configure)
    # Create system user
    adduser --system --group \
            --home "$DATA_DIR" \
            --no-create-home \
            --shell /usr/sbin/nologin \
            x2fa || true

    # Create directories
    install -d -m 700 -o x2fa -g x2fa "$DATA_DIR"
    install -d -m 750 -o x2fa -g adm  "$LOG_DIR"
    install -d -m 750 -o x2fa -g x2fa "$CONFIG_DIR"

    # Copy default config stubs (never overwrite operator edits)
    for src in "$VENV"/lib/python3*/site-packages/x2fa/config_files/*.toml; do
        dest="$CONFIG_DIR/$(basename "$src")"
        if [ ! -f "$dest" ]; then
            cp "$src" "$dest"
            chown x2fa:x2fa "$dest"
            chmod 640 "$dest"
        fi
    done

    # Fresh install: initialise DB and signing keys
    if [ -z "$2" ]; then
        echo "Initialising X2FA database and signing keys..."
        X2FA_CONFIG_DIR="$CONFIG_DIR" \
         \
            su -s /bin/sh x2fa -c "$FLASK init-db"
        X2FA_CONFIG_DIR="$CONFIG_DIR" \
         \
            su -s /bin/sh x2fa -c "$FLASK init-keys"
    fi

    # Upgrade: run migrations (once Alembic is added)
    # X2FA_CONFIG_DIR="$CONFIG_DIR"  \
    #     su -s /bin/sh x2fa -c "$FLASK db upgrade"

    systemctl daemon-reload || true

    echo ""
    echo "X2FA installed. Run 'x2fa-install' to complete initial configuration,"
    echo "then: systemctl enable --now x2fa"
    ;;
esac
```

### 4.7 `debian/prerm`

```bash
#!/bin/bash
set -e
case "$1" in
  remove|upgrade)
    systemctl stop x2fa 2>/dev/null || true
    systemctl disable x2fa 2>/dev/null || true
    ;;
esac
```

### 4.8 `debian/conffiles`

```
/etc/x2fa/x2fa_config.toml
/etc/x2fa/db_config.toml
/etc/x2fa/security_config.toml
/etc/x2fa/ratelimit_config.toml
/etc/x2fa/babel_config.toml
```

Declaring these as `conffiles` causes `dpkg` to prompt before overwriting
operator-modified files during upgrades.

### 4.9 Building

```bash
# On Debian 12 build machine
apt install dh-virtualenv debhelper devscripts lintian
dpkg-buildpackage -us -uc -b
lintian ../x2fa_2.0.0_amd64.deb
```

---

## 5. Channel C — AppImage

### 5.1 Requirements

| Tool | Version | Notes |
|---|---|---|
| `python-appimage` | ≥ 1.2 | Wraps a Python wheel into an AppImage |
| `appimagetool` | ≥ 13 | Low-level AppImage assembler |
| `FUSE` | 2 or 3 | On the target system (available by default on all modern distros) |
| `uv build` | — | Produces the wheel to bundle |

### 5.2 AppRun script

The AppImage entry point dispatches between modes:

```bash
#!/bin/bash
# AppRun — entry point for the X2FA AppImage

HERE="$(dirname "$(readlink -f "$0")")"
PYTHON="$HERE/usr/bin/python3"
export PYTHONPATH="$HERE/usr/lib/python3.11/site-packages:$PYTHONPATH"
export X2FA_CONFIG_DIR="${X2FA_CONFIG_DIR:-$HOME/.config/x2fa}"

case "${1:-install}" in
  server)
    # Start Gunicorn — pass remaining args
    exec "$PYTHON" -m gunicorn x2fa.wsgi:app \
        --bind "127.0.0.1:5000" "${@:2}"
    ;;
  flask)
    # Admin CLI — e.g. ./x2fa.AppImage flask add-client …
    export FLASK_APP=x2fa.wsgi
    export 
    exec "$PYTHON" -m flask "${@:2}"
    ;;
  install|*)
    # Default: TUI installer
    exec "$PYTHON" -m installer
    ;;
esac
```

### 5.3 `appimage-builder.yml` recipe

```yaml
version: 1

AppDir:
  path: AppDir

  app_info:
    id: io.github.your-org.x2fa
    name: x2fa
    icon: x2fa
    version: "2.0.0"
    exec: usr/bin/python3
    exec_args: "$APPDIR/AppRun $@"

  apt:
    arch: amd64
    sources:
      - sourceline: "deb http://deb.debian.org/debian bookworm main"
    include:
      - python3.11
      - python3.11-venv
      - libssl3
      - libffi8

  files:
    include:
      - usr/lib/python3.11
    exclude:
      - usr/share/doc
      - usr/share/man

  test:
    fedora-38:
      image: fedora:38
      command: "./AppRun flask --version"
    ubuntu-22:
      image: ubuntu:22.04
      command: "./AppRun flask --version"

AppImage:
  arch: x86_64
  update-information: "gh-releases-zsync|your-org|x2fa|latest|x2fa-*x86_64.AppImage.zsync"
  sign-key: YOUR_GPG_KEY_ID
```

### 5.4 Build script (`scripts/build_appimage.sh`)

```bash
#!/bin/bash
set -euo pipefail

VERSION=$(python3 -c \
  "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")

# 1. Build wheel
uv build --wheel

# 2. Install wheel into AppDir
pip install \
    --target AppDir/usr/lib/python3.11/site-packages \
    dist/x2fa-"${VERSION}"-py3-none-any.whl

# 3. Copy AppRun and desktop integration files
cp scripts/AppRun AppDir/AppRun
chmod +x AppDir/AppRun
cp assets/x2fa.desktop AppDir/
cp assets/x2fa.png     AppDir/

# 4. Assemble
appimage-builder --recipe appimage-builder.yml --skip-tests
```

### 5.5 Limitations

- FUSE 2 is required; `--appimage-extract-and-run` is the fallback on systems
  where FUSE is unavailable (e.g. restricted CI)
- No integration with system package managers — no automatic security updates
- The bundled CPython must be rebuilt when CVEs affect Python itself
- AppImage size: approximately 45 MB compressed for Python 3.11 + all dependencies

---

## 6. Channel D — OCI Container Image

### 6.1 Requirements

| Tool | Version | Notes |
|---|---|---|
| Docker or Podman | ≥ 24 / ≥ 4 | Image build and run |
| `cosign` | ≥ 2.0 | Image signing (Sigstore) |
| GitHub Actions | — | Build + push automation |

### 6.2 `Dockerfile`

Multi-stage build keeps the final image minimal:

```dockerfile
# ── Stage 1: build wheel ──────────────────────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir build && python -m build --wheel

# ── Stage 2: runtime ──────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

RUN adduser --system --group --no-create-home x2fa

# Install wheel
COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Runtime environment
ENV  \
    X2FA_CONFIG_DIR=/etc/x2fa \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Config and data are mounted — create mountpoint directories
RUN install -d -m 750 -o x2fa -g x2fa /etc/x2fa /var/lib/x2fa

EXPOSE 5000
USER x2fa
WORKDIR /var/lib/x2fa

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 -c \
    "import urllib.request; \
     urllib.request.urlopen('http://localhost:5000/.well-known/openid-configuration')"

ENTRYPOINT ["x2fa-server"]
CMD ["--bind", "0.0.0.0:5000", "--workers", "4"]
```

### 6.3 `docker-compose.yml`

A complete self-hosted stack:

```yaml
services:
  x2fa:
    image: ghcr.io/your-org/x2fa:2.0.0
    restart: unless-stopped
    ports:
      - "127.0.0.1:5000:5000"
    volumes:
      - ./config:/etc/x2fa:ro        # read-only at runtime
      - x2fa-data:/var/lib/x2fa
    environment:
      X2FA_CONFIG_DIR: /etc/x2fa
    depends_on:
      redis:
        condition: service_healthy
      init:
        condition: service_completed_successfully

  init:
    image: ghcr.io/your-org/x2fa:2.0.0
    user: x2fa
    volumes:
      - ./config:/etc/x2fa
      - x2fa-data:/var/lib/x2fa
    environment:
      X2FA_CONFIG_DIR: /etc/x2fa
    command: >
      sh -c "flask --app x2fa.wsgi init-db &&
             flask --app x2fa.wsgi init-keys"
    restart: "no"

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/x2fa.conf:ro
      - ./certs:/etc/ssl/x2fa:ro
    depends_on:
      - x2fa

volumes:
  x2fa-data:
```

### 6.4 Init container pattern (Kubernetes)

```yaml
initContainers:
  - name: x2fa-init
    image: ghcr.io/your-org/x2fa:2.0.0
    env:
      - name: X2FA_CONFIG_DIR
        value: /etc/x2fa
    command:
      - sh
      - -c
      - |
        flask --app x2fa.wsgi init-db
        flask --app x2fa.wsgi init-keys
    volumeMounts:
      - name: x2fa-config
        mountPath: /etc/x2fa
      - name: x2fa-data
        mountPath: /var/lib/x2fa
```

### 6.5 TUI installer in container context

The TUI installer requires an interactive terminal and a writable filesystem.
It must not run inside the container. Instead:

1. Run the installer on the host to produce the config directory:
   ```bash
   pip install "x2fa[installer]"
   X2FA_CONFIG_DIR=./config x2fa-install
   ```
2. Mount `./config` as `/etc/x2fa` in the container (read-only after init).

The installer should detect a non-TTY environment (`not sys.stdin.isatty()`) and
exit with a clear message rather than crashing Textual.

---

## 7. Shared Concerns

### 7.1 Config file precedence (all channels)

```
environment variables        ← highest — containers, CI, overrides
  ↓
$X2FA_CONFIG_DIR/*.toml      ← /etc/x2fa for system installs
  ↓
package defaults             ← [default] sections shipped in the wheel
```

Dynaconf's `environments=True` + `envvar_prefix` already implements this layering.
Only `_config_root()` in `config.py` needs updating (see §2.1).

### 7.2 Signing and provenance

| Channel | Mechanism | Key management |
|---|---|---|
| PyPI | Trusted publishing (OIDC) | No API key stored in CI |
| Debian `.deb` | GPG-signed `Release` file in apt repo | Offline key, subkey for CI signing |
| AppImage | `appimagetool --sign` | Same GPG key as Debian |
| OCI image | `cosign` (keyless, Sigstore) | OIDC identity, no private key in CI |

### 7.3 Security hardening in packaged deployments

All packaging channels should apply the same hardening defaults:

- **systemd unit:** `PrivateTmp=true`, `NoNewPrivileges=true`, `ProtectSystem=strict`,
  `ReadWritePaths=` restricted to `/var/lib/x2fa /var/log/x2fa /etc/x2fa`
- **Container:** non-root user, `--cap-drop ALL`, read-only root filesystem with
  explicit `tmpfs` mounts for `/tmp`
- **CA private keys** (`/etc/x2fa/*.key.pem`) must be `chmod 600`, owned by `x2fa`,
  and are never bundled in images or packages

### 7.4 Alembic migration — full scope

Until this is implemented, every packaging channel carries the following caveat:
*"upgrading to a version that adds new columns requires manual ALTER TABLE".*

Steps to add Alembic:

```bash
# 1. Add dependencies
uv add alembic flask-migrate

# 2. Initialise the migration environment (once)
flask --app x2fa.wsgi db init     # creates migrations/ directory

# 3. Generate first migration from current models
flask --app x2fa.wsgi db migrate -m "initial schema"
flask --app x2fa.wsgi db upgrade

# 4. Future schema changes generate new migration scripts automatically
flask --app x2fa.wsgi db migrate -m "add client_cert_fingerprint"
flask --app x2fa.wsgi db upgrade
```

`flask init-db` is kept but renamed to `flask init-db --force` with an explicit
confirmation prompt, to prevent accidental use on an existing installation.

---

## 8. Recommended Implementation Order

| Step | Work item | Blocks | Effort |
|---|---|---|---|
| 1 | Externalize `X2FA_CONFIG_DIR` (§2.1–2.4) | All channels | 1–2 days |
| 2 | PyPI wheel + release CI (§3) | Debian, AppImage | 1 week |
| 3 | OCI image + `docker-compose.yml` (§6) | — | 2 days |
| 4 | Alembic migrations (§2.3, §7.4) | Stable upgrades | 1 week |
| 5 | Debian package (§4) | — | 1 week |
| 6 | AppImage (§5) | — | 3 days |

Steps 3–4 and 5–6 can be parallelised once step 2 is done.
Alembic (step 4) can be developed in parallel with steps 3–6 but must land before
any channel publishes a stable release.
