# X2FA Packaging Proposal

## Context

X2FA consists of two logical components:

| Component | Location | Role |
|---|---|---|
| Application | `src/x2fa/` | Flask/Gunicorn WSGI service |
| Installer | `installer/` | Textual TUI configuration wizard |

Both are already described in `pyproject.toml` as a single project with an optional
`installer` extra and a `x2fa-install` entry-point script.  The packaging options below
differ mainly in how they solve three constraints:

1. **Runtime interpreter** — Gunicorn + the Flask app need Python ≥ 3.11.
2. **Config-file templates** — `installer/config_writer.py` locates default TOML files
   via `Path(__file__).resolve().parent.parent / "src" / "x2fa" / "config_files"`.
   This path is repo-relative and breaks once the package is installed anywhere else.
   **All options below require fixing this to `importlib.resources` first.**
3. **`WorkingDirectory` in the systemd unit** — currently set to `install_root` (the repo
   clone). For installed packages this must become the directory that actually contains
   `wsgi.py`, which after packaging is the importable package root, not a checkout.

---

## Option A — PyPI Wheel (recommended for most cases)

### What it is

A standard Python wheel published to PyPI (or a private index).
Users install with:

```bash
pip install x2fa[installer]          # full: app + TUI installer
pip install x2fa                     # app only
uv add x2fa[installer]               # via uv
```

The `x2fa-install` entry-point runs the TUI installer; Gunicorn is launched normally
via `uv run gunicorn` or the system `gunicorn` binary once the package is in the venv.

### Build

```bash
uv build                             # produces dist/x2fa-2.0.0.tar.gz + .whl
uv publish                           # uploads to PyPI (needs PYPI_TOKEN)
```

`uv build` calls the PEP 517 build backend declared in `pyproject.toml` (`setuptools`
by default) and produces an sdist and a wheel.

### Required changes

1. **Fix `config_writer.py` template path** (blocker for all options):

   ```python
   # Before (repo-relative — breaks after install)
   template_dir = Path(__file__).resolve().parent.parent / "src" / "x2fa" / "config_files"

   # After (importlib.resources — works in wheels and editable installs)
   from importlib.resources import files
   template_dir = files("x2fa") / "config_files"
   ```

2. **Fix `WorkingDirectory` in the generated systemd unit** — replace `cfg.install_root`
   with the installed package location:

   ```python
   from importlib.resources import files
   install_root = Path(str(files("x2fa"))).parent
   ```

3. **Mark `installer/` as a package** — ensure `pyproject.toml` includes it in the wheel:

   ```toml
   [tool.setuptools.packages.find]
   where = ["src", "."]
   include = ["x2fa*", "installer*"]
   ```

   Currently `installer` is not excluded, but verifying it is included in the built wheel
   is necessary (run `tar tzf dist/x2fa-*.tar.gz | grep installer`).

### Pros / Cons

| Pros | Cons |
|---|---|
| Standard Python workflow | Requires Python + pip/uv on target |
| `uv tool install x2fa[installer]` gives an isolated, globally available `x2fa-install` | Runtime still needs `uv` for `uv run gunicorn` unless Gunicorn is invoked directly |
| PyPI or private Gitea/Nexus package index possible | Users must manage Python versions themselves |

---

## Option B — Docker / OCI Container

### What it is

A Docker image that bundles the application, Python runtime, and all dependencies.
The installer TUI is not included in the container — configuration is handled by
mounting pre-written config files or by passing environment variables.

### Dockerfile sketch

```dockerfile
FROM python:3.11-slim AS build
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-extra installer
COPY src/ src/
COPY migrations/ migrations/

FROM python:3.11-slim
WORKDIR /app
COPY --from=build /app /app
ENV ENV_FOR_DYNACONF=production
EXPOSE 5000
CMD [".venv/bin/gunicorn", "x2fa.wsgi:app", "--bind", "0.0.0.0:5000"]
```

A `compose.yml` would mount `~/.config/x2fa/` and `~/.local/share/x2fa/` as volumes so
that configuration and the SQLite database survive container restarts.

The installer TUI can be shipped as a separate image or run as a one-off container
(`docker run --rm -it -v $HOME/.config/x2fa:/root/.config/x2fa x2fa-installer`).

### Required changes

1. Fix the `config_writer.py` template path (same as Option A).
2. Write `compose.yml` with volume mounts for config and data directories.
3. Add a `.dockerignore` to exclude `tests/`, `docs/`, `demo_rp/`, `.git/`.
4. The installer TUI needs a TTY — document `docker run -it` usage or ship it
   as a helper script that mounts the right directories.

### Pros / Cons

| Pros | Cons |
|---|---|
| Self-contained; no Python on host | TUI installer needs extra steps (TTY, volume mounts) |
| Trivial to deploy on any Linux / k8s | Config still lives outside the container (volumes) |
| Easy to version and roll back | Image size (~200 MB); multi-worker needs Redis volume too |
| Works well in CI | Less transparent for operators who read config files directly |

---

## Option C — Podman (rootless, Quadlet)

### What it is

Podman is a daemonless OCI runtime that runs containers as the current unprivileged user.
It uses the **same `Dockerfile`** as Option B — no changes needed to the image build.

The key difference is service management: instead of a Compose daemon, Podman integrates
natively with systemd via **Quadlet** unit files (`.container`, `.volume`) placed in
`~/.config/containers/systemd/`.  Systemd reads these files and manages the container
exactly like any other user service.

### Build

```bash
podman build -t x2fa:latest .      # identical to docker build
```

### Quadlet files

Three files live in `podman/`:

| File | Purpose |
|---|---|
| `x2fa.container` | Systemd service unit that runs the container |
| `x2fa-config.volume` | Named volume for `~/.config/x2fa/` (TOML files) |
| `x2fa-data.volume` | Named volume for `~/.local/share/x2fa/` (DB, CA key) |

### Install workflow

```bash
# 1. Build the image
podman build -t x2fa:latest .

# 2. Run the installer TUI once to generate config and initialise the database
podman run -it --rm \
  -v x2fa-config:/home/x2fa/.config/x2fa:Z \
  -v x2fa-data:/home/x2fa/.local/share/x2fa:Z \
  localhost/x2fa:latest x2fa-install

# 3. Install Quadlet files
cp podman/*.container podman/*.volume ~/.config/containers/systemd/

# 4. Enable and start
systemctl --user daemon-reload
systemctl --user enable --now x2fa.service

# 5. Auto-start on boot without interactive login
loginctl enable-linger
```

### Upgrading

```bash
podman build -t x2fa:latest .
systemctl --user restart x2fa.service
```

### Key differences from Docker (Option B)

| Topic | Docker | Podman |
|---|---|---|
| Daemon | `dockerd` required | None |
| Default privilege | root (unless configured) | Current user (rootless) |
| Service wiring | `compose.yml` + Compose plugin | Quadlet → native systemd unit |
| Volume SELinux label | Not needed | `:Z` required on Fedora/RHEL |
| Local image ref | `x2fa:latest` | `localhost/x2fa:latest` |
| Compose support | `docker compose` | `podman-compose` works but not idiomatic |

### Required changes

None beyond what Option B already requires.  The `Dockerfile` and `.dockerignore` are
shared.  The only Podman-specific artifacts are the three files in `podman/`.

### Pros / Cons

| Pros | Cons |
|---|---|
| No daemon; lower attack surface | Quadlet requires Podman ≥ 4.4 and systemd |
| Rootless by default | `:Z` SELinux labels needed on Fedora/RHEL |
| Native systemd integration — no extra tooling | `localhost/` prefix on local image refs surprises Docker users |
| Same `Dockerfile` as Option B | `podman-compose` exists but is a third-party wrapper |
| Ideal for user-space server deployments | |

---

## Option D — Standalone Zipapp via `shiv`

### What it is

`shiv` packages the application and all its dependencies into a single `.pyz` file
(a Python zipapp).  The file is self-contained and executable:

```bash
./x2fa.pyz                             # starts Gunicorn
./x2fa-install.pyz                     # runs the installer TUI
```

A Python interpreter must still be present on the target system (≥ 3.11), but no
package manager, no venv, and no internet access is needed after the `.pyz` is copied.

### Build

```bash
pip install shiv
uv export --no-dev --no-extra installer -o requirements.txt
shiv -c "gunicorn" -o dist/x2fa.pyz -r requirements.txt .

uv export --extra installer --no-dev -o requirements-installer.txt
shiv -c "installer.__main__:main" -o dist/x2fa-install.pyz -r requirements-installer.txt .
```

`shiv` extracts the zipapp into `~/.shiv/<hash>/` on first run (a few seconds), then
subsequent runs use the cached extraction.

### Required changes

1. Fix `config_writer.py` template path (same as Option A) — zipapps cannot open files
   inside themselves at arbitrary paths; `importlib.resources` is mandatory.
2. The `WorkingDirectory` in the generated systemd unit cannot be the zipapp itself;
   it should be set to the directory containing the `.pyz` file or to the
   data directory (`~/.local/share/x2fa/`).
3. Add a `Makefile` or `build.sh` to automate the two-phase build.

### Pros / Cons

| Pros | Cons |
|---|---|
| Single file, easy to distribute (scp, Ansible, USB) | First-run extraction delay (~5 s) |
| No pip/uv needed on target | Python 3.11+ still required on target |
| Works offline after delivery | Gunicorn worker fork inside a zipapp can be tricky on some platforms |
| Suitable for air-gapped environments | Larger file than a wheel (~40–60 MB) |

---

## Option E — Debian `.deb` Package (via `dh-virtualenv`)

### What it is

A proper `.deb` that integrates with `apt`, installs into `/opt/x2fa/`, ships a
systemd unit in `/lib/systemd/system/`, and creates the `x2fa` system user on install.

`dh-virtualenv` builds a Debian package that contains a complete Python virtualenv
alongside the application code.

### Build

```
apt install dh-virtualenv devscripts build-essential
dh_make --single --packagename x2fa_2.0.0
# edit debian/control, debian/x2fa.service, debian/postinst
dpkg-buildpackage -us -uc
```

`debian/postinst` would run `flask init-db` and `flask init-keys` after install.

### Required changes

1. Fix `config_writer.py` template path.
2. Write `debian/` directory: `control`, `rules`, `install`, `postinst`, `prerm`,
   `x2fa.service`.
3. The installer TUI needs an `ExecStartPre` or a separate `.deb` package.
4. The `dh-virtualenv` approach vendors all dependencies into the `.deb`, making it
   large (~80–120 MB) and requiring a rebuild on each dependency update.

### Pros / Cons

| Pros | Cons |
|---|---|
| First-class Debian citizen: `apt install x2fa` | Significant packaging overhead |
| `postinst` can create user, run migrations, enable service | Tight coupling to Debian version |
| Upgrade path via `apt upgrade` | `dh-virtualenv` is a non-standard tool |
| Appropriate for enterprise / Debian-maintained deployments | Rebuilds required for dependency CVE patches |

---

## Comparison Matrix

| | A — Wheel | B — Docker | C — Podman | D — Shiv | E — .deb |
|---|---|---|---|---|---|
| **Python required on target** | Yes | No | No | Yes | No |
| **Installer TUI works** | Yes | With effort | With effort | Yes | With effort |
| **Single-file delivery** | No | Image | Image | Yes | Yes |
| **Offline deployment** | No (needs index) | Yes (save/load) | Yes (save/load) | Yes | Yes |
| **System integration (user, service)** | Manual | Compose daemon | Native systemd | Manual | Automatic |
| **Rootless by default** | Yes | No | Yes | Yes | No |
| **Upgrade path** | `pip install -U` | `docker pull` | `podman pull` | Replace file | `apt upgrade` |
| **Build complexity** | Low | Medium | Medium | Medium | High |

---

## Recommendation

**Short term: Option A (wheel)**

The project is already 90% ready for a wheel build.  The one required code change
(the `config_writer.py` template path) is a two-line fix.  Publishing to PyPI (or a
private Gitea package registry) gives operators `uv tool install x2fa[installer]` and
a clean upgrade path.

**Medium term: Option B (Docker) or C (Podman) alongside A**

Both produce the same OCI image from the same `Dockerfile`.  Choose based on the target
environment:

- **Docker (B)** — when the server already runs Docker or when Kubernetes/Compose
  workflows are preferred.
- **Podman (C)** — when rootless containers and native systemd integration are
  preferred, or on Fedora/RHEL systems where Podman ships by default.  The Quadlet
  files in `podman/` give a cleaner systemd integration than any Compose setup.

**Option D (shiv)** is worth adding as a CI artifact once A is done —
it costs one extra build step and gives an air-gapped / Ansible-friendly delivery
artifact for free.

**Option E (.deb)** should only be pursued if there is a concrete requirement to
integrate with a Debian/Ubuntu package repository or a configuration management system
that relies on `apt`.

---

## Prerequisite fixes (done)

The following repo-relative paths were fixed as part of implementing Options A–C:

- `installer/config_writer.py` — now uses `importlib.resources.files("x2fa")` to locate
  config-file templates; works in wheels, editable installs, and containers.
- `src/x2fa/cli.py` — same treatment for the Alembic migrations directory.
- `migrations/` — moved into `src/x2fa/migrations/` so it ships inside the wheel and is
  accessible via `importlib.resources` in all deployment scenarios.
