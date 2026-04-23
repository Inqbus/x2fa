"""Installer configuration model - holds user choices only."""
import json
from dataclasses import dataclass, field
from pathlib import Path

# Fields excluded from session persistence.
# - generated_files, install_error: transient results from a previous run
_SESSION_EXCLUDE = {"generated_files", "install_error", "client_secret"}


@dataclass
class InstallConfig:
    """Configuration for the X2FA installer.

    Holds user choices only (domain, CA CN, auth method, etc.).
    All path resolution is delegated to x2fa.paths.get_home() and friends.
    """

    # ── Database ──────────────────────────────────────────────────────────
    db_type: str = "sqlite"  # sqlite | postgres | mysql
    db_uri: str = ""  # left blank → auto-filled from db_type

    # ── Domain & Reverse Proxy ────────────────────────────────────────────
    domain: str = ""
    proxy_type: str = "caddy"  # caddy | nginx | traefik | other

    # ── Security ──────────────────────────────────────────────────────────
    secret_key: str = ""  # auto-generated on SecurityScreen
    secret_salt: str = ""  # auto-generated on SecurityScreen
    use_redis: bool = False
    redis_uri: str = "redis://localhost:6379/0"

    # ── Certificate Authority ─────────────────────────────────────────────
    ca_action: str = "generate"  # generate | import
    ca_name: str = "x2fa-internal-ca"
    ca_cn: str = "X2FA Internal CA"
    ca_validity_days: int = 3650
    ca_import_path: str = ""  # used when ca_action == "import"

    # ── First OIDC Client ─────────────────────────────────────────────────
    client_id: str = ""
    client_redirect_uri: str = ""
    client_auth_method: str = "tls_client_auth"
    client_jwks_uri: str = ""  # private_key_jwt
    client_self_signed_cert_path: str = ""  # self_signed_tls_client_auth

    # ── Deployment options ────────────────────────────────────────────────
    enable_systemd: bool = True   # attempt systemctl --user enable --now after install

    # ── Results (filled during ExecuteScreen) ─────────────────────────────
    generated_files: list[str] = field(default_factory=list)
    install_error: str | None = None
    # Plaintext client secret — only set for client_secret_* methods.
    # Excluded from session persistence (never written to disk).
    client_secret: str = ""

    def effective_db_uri(self) -> str:
        from x2fa import paths

        if self.db_uri:
            return self.db_uri
        return f"sqlite:///{paths.db_path()}"

    def effective_ca_cert(self) -> str:
        """Return the CA cert path only if the file actually exists on disk.

        Returns an empty string when no CA was created.
        """
        import os
        from x2fa import paths

        path = paths.ca_cert_path() if self.ca_action == "generate" else self.ca_import_path
        if not path:
            return ""
        return path if os.path.exists(path) else ""

    # ── Session persistence ───────────────────────────────────────────────

    @staticmethod
    def session_file() -> str:
        """Location of the installer session file.

        Uses X2FA_HOME via paths.py for test isolation.
        """
        from x2fa import paths
        return str(paths.data_dir() / "installer_session.json")

    def save_session(self) -> None:
        """Persist all user-entered fields to the session file."""
        import json

        data: dict = {}
        for f in self.__dataclass_fields__:
            if f in _SESSION_EXCLUDE:
                continue
            val = getattr(self, f)
            data[f] = str(val) if isinstance(val, Path) else val
        sf = InstallConfig.session_file()
        sf_path = Path(sf)
        sf_path.parent.mkdir(parents=True, exist_ok=True)
        sf_path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load_session(cls) -> "InstallConfig":
        """Load a previously saved session, falling back to defaults on any error."""
        import json
        import sys

        sf_path = Path(cls.session_file())
        if sf_path.exists():
            try:
                data = json.loads(sf_path.read_text())
                return cls(**data)
            except (json.JSONDecodeError, TypeError) as exc:
                print(f"Warning: installer session file is corrupted ({exc}); starting fresh.", file=sys.stderr)
            except Exception as exc:
                print(f"Warning: could not load installer session ({exc}); starting fresh.", file=sys.stderr)
        return cls()
