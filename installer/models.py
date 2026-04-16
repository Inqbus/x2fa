import os
from dataclasses import dataclass, field
from pathlib import Path


def _get_default_paths() -> tuple[str, str, str, str]:
    """Return LSB/XDG-compliant default paths"""

    # Non-root: XDG Base Directory spec
    # Config: ~/.config/x2fa/, Data: ~/.local/share/x2fa/
    xdg_data = Path.home() / ".local" / "share" / "x2fa"
    xdg_data.mkdir(parents=True, exist_ok=True)
    return (
        str(xdg_data / "ca_key.pem"),
        str(xdg_data / "ca_cert.pem"),
        str(xdg_data / "db.sqlite"),
        str(xdg_data),
    )


@dataclass
class InstallConfig:
    # Installation root (X2FA repo root — assumed to be cwd)
    install_root: Path = field(default_factory=Path.cwd)

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
    ca_key_path: str = field(default_factory=lambda: _get_default_paths()[0])
    ca_cert_path: str = field(default_factory=lambda: _get_default_paths()[1])
    ca_import_path: str = ""  # used when ca_action == "import"

    # ── First OIDC Client ─────────────────────────────────────────────────
    client_id: str = ""
    client_redirect_uri: str = ""
    client_auth_method: str = "tls_client_auth"
    client_jwks_uri: str = ""  # private_key_jwt
    client_self_signed_cert_path: str = ""  # self_signed_tls_client_auth
    client_cert_output_dir: str = "."  # tls_client_auth

    # ── Results (filled during ExecuteScreen) ─────────────────────────────
    generated_files: list[str] = field(default_factory=list)
    install_error: str | None = None

    def effective_db_uri(self) -> str:
        if self.db_uri:
            return self.db_uri
        default = _get_default_paths()[2]
        return f"sqlite:///{default}"

    def effective_ca_cert(self) -> str:
        return (
            self.ca_cert_path if self.ca_action == "generate" else self.ca_import_path
        )
