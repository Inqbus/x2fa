# todos

#### wishlist

* Write unit tests for installer (`installer/screens/*.py`, `installer/config_writer.py`, `installer/runner.py`, `installer/models.py`)
  * ✅ `test_installer_models.py` - 11 tests for InstallConfig and XDG paths
* When Flask CLI or web app starts and config files are missing, raise a clear RuntimeError with instructions to run the installer.
* Move CA keys/certs from source tree to XDG data directory (`~/.local/share/x2fa/`)
* Add Alembic migrations for safe schema upgrades (produces `ALTER TABLE` for existing installations, replaces destructive `flask init-db`)
* Add support for additional OIDC client authentication methods:
  * `self_signed_tls_client_auth` (self-signed cert fingerprint pinning)
  * `client_secret_jwt` (HMAC-signed JWT)
  * `client_secret_post` / `client_secret_basic` (shared secrets)
* Externalize template folder path for multi-stage Docker builds (use `importlib.resources`)
* Remove `client_secret` column and related code from `OIDCClient` model and CLI commands
