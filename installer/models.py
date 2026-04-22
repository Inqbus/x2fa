import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Fields excluded from session persistence.
# - install_root: derived from cwd at runtime
# - x2fa_home: CLI argument; saving it causes the session file location to follow a
#   stale path (e.g. a pytest tmp dir) instead of always resolving via Path.home()
# - generated_files, install_error: transient results from a previous run
_SESSION_EXCLUDE = {"install_root", "x2fa_home", "generated_files", "install_error", "client_secret"}


@dataclass
class InstallConfig:
    # Installation root (X2FA repo root — assumed to be cwd)
    install_root: Path = field(default_factory=Path.cwd)

    # Root directory for LSB/XDG paths (default: home directory).
    # Override via --config-root to change where config and data files land.
    # Config:  <x2fa_home>/.config/x2fa/
    # Data:    <x2fa_home>/.local/share/x2fa/
    x2fa_home: Path = field(default_factory=Path.home)

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
    ca_key_path: str = ""   # filled by __post_init__ from x2fa_home
    ca_cert_path: str = ""  # filled by __post_init__ from x2fa_home
    ca_import_path: str = ""  # used when ca_action == "import"

    # ── First OIDC Client ─────────────────────────────────────────────────
    client_id: str = ""
    client_redirect_uri: str = ""
    client_auth_method: str = "tls_client_auth"
    client_jwks_uri: str = ""  # private_key_jwt
    client_self_signed_cert_path: str = ""  # self_signed_tls_client_auth
    client_cert_output_dir: str = ""   # tls_client_auth — filled by __post_init__

    # ── Deployment options ────────────────────────────────────────────────
    enable_systemd: bool = True   # attempt systemctl --user enable --now after install

    # ── Results (filled during ExecuteScreen) ─────────────────────────────
    generated_files: list[str] = field(default_factory=list)
    install_error: str | None = None
    # Plaintext client secret — only set for client_secret_* methods.
    # Excluded from session persistence (never written to disk).
    client_secret: str = ""

    def __post_init__(self) -> None:
        data = self._data_dir()
        if not self.ca_key_path:
            self.ca_key_path = str(data / "ca_key.pem")
        if not self.ca_cert_path:
            self.ca_cert_path = str(data / "ca_cert.pem")
        if not self.client_cert_output_dir:
            self.client_cert_output_dir = str(data)

    def _data_dir(self) -> Path:
        """XDG data directory: <x2fa_home>/.local/share/x2fa/"""
        return self.x2fa_home / ".local" / "share" / "x2fa"

    def _config_dir(self) -> Path:
        """XDG config directory: <x2fa_home>/.config/x2fa/"""
        return self.x2fa_home / ".config" / "x2fa"

    def effective_db_uri(self) -> str:
        if self.db_uri:
            return self.db_uri
        return f"sqlite:///{self._data_dir() / 'db.sqlite'}"

    def effective_ca_cert(self) -> str:
        """Return the CA cert path only if the file actually exists on disk.

        Returns an empty string when no CA was created (e.g. client_secret_*
        installations never run the CA step, so the default path is set but
        the file is absent).
        """
        path = self.ca_cert_path if self.ca_action == "generate" else self.ca_import_path
        if not path:
            return ""
        return path if Path(path).exists() else ""

    # ── Session persistence ───────────────────────────────────────────────

    @staticmethod
    def session_file(x2fa_home: Path | None = None) -> Path:
        """Location of the installer session file.

        Uses *x2fa_home* when supplied (so test fixtures stay isolated),
        otherwise falls back to the user's home directory.
        """
        root = x2fa_home if x2fa_home is not None else Path.home()
        return root / ".local" / "share" / "x2fa" / "installer_session.json"

    def save_session(self) -> None:
        """Persist all user-entered fields to the session file."""
        data: dict = {}
        for f in self.__dataclass_fields__:
            if f in _SESSION_EXCLUDE:
                continue
            val = getattr(self, f)
            data[f] = str(val) if isinstance(val, Path) else val
        sf = self.session_file(self.x2fa_home)
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(data, indent=2))

    @classmethod
    def load_session(cls, install_root: Path, x2fa_home: Path | None = None) -> "InstallConfig":
        """Load a previously saved session, falling back to defaults on any error."""
        import sys
        sf = cls.session_file(x2fa_home)
        if sf.exists():
            try:
                data = json.loads(sf.read_text())
                data.pop("config_root", None)   # never restore; always use runtime arg
                kwargs_cr = {"x2fa_home": x2fa_home} if x2fa_home is not None else {}
                return cls(install_root=install_root, **kwargs_cr, **data)
            except json.JSONDecodeError as exc:
                print(f"Warning: installer session file is corrupted ({exc}); starting fresh.", file=sys.stderr)
            except Exception as exc:
                print(f"Warning: could not load installer session ({exc}); starting fresh.", file=sys.stderr)
        kwargs: dict = {"install_root": install_root}
        if x2fa_home is not None:
            kwargs["x2fa_home"] = x2fa_home
        return cls(**kwargs)
