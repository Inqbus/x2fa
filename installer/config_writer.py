import tomli_w
from importlib.resources import files as _pkg_files
from pathlib import Path

from installer.models import InstallConfig

_SYSTEMD_UNIT = """\
[Unit]
Description=X2FA FIDO2 Authentication Microservice
After=network.target

[Service]
Type=simple
WorkingDirectory={install_root}
ExecStart=uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def write_systemd_unit(config: InstallConfig) -> tuple[bool, str]:
    """Write ~/.config/systemd/user/x2fa.service. Returns (success, log_message)."""
    unit_dir = config.x2fa_home / ".config" / "systemd" / "user"
    unit_path = unit_dir / "x2fa.service"
    try:
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(
            _SYSTEMD_UNIT.format(install_root=config.install_root)
        )
        unit_path.chmod(0o644)
        return True, f"Service file written: {unit_path}"
    except OSError as exc:
        return False, f"Failed to write systemd unit: {exc}"


def write_configs(config: InstallConfig) -> tuple[bool, str]:
    """Write all TOML config files to XDG config directory. Returns (success, log_message)."""
    config_dir = config._config_dir()
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

    template_dir = Path(str(_pkg_files("x2fa").joinpath("config_files")))

    written: list[str] = []
    try:
        storage = config.redis_uri if config.use_redis else "memory://"

        # Files that need [production] section added
        files_with_production = {
            "security_config.toml": {
                "production": {
                    "SECRET_KEY": config.secret_key,
                    "SECRET_SALT": config.secret_salt,
                    "SESSION_COOKIE_SECURE": True,
                    "SESSION_COOKIE_HTTPONLY": True,
                    "SESSION_COOKIE_SAMESITE": "Lax",
                    "PERMANENT_SESSION_LIFETIME": 600,
                },
            },
            "x2fa_config.toml": {
                "production": {
                    "DOMAIN": config.domain,
                    "ORIGIN": f"https://{config.domain}",
                    "TESTING": False,
                },
            },
            "db_config.toml": {
                "production": {
                    "SQLALCHEMY_DATABASE_URI": config.effective_db_uri(),
                },
            },
            "ratelimit_config.toml": {
                "production": {
                    "RATELIMIT_STORAGE_URI": storage,
                    "RATELIMIT_STRATEGY": "moving-window",
                    "RATELIMIT_HEADERS_ENABLED": True,
                },
            },
        }

        # Copy babel_config.toml without changes
        import tomllib

        babel_src = template_dir / "babel_config.toml.default"
        babel_dest = config_dir / "babel_config.toml"
        if babel_src.exists():
            babel_dest.write_text(babel_src.read_text())
            babel_dest.chmod(0o644)
            written.append(str(babel_dest))

        for filename, new_section in files_with_production.items():
            src_path = template_dir / f"{filename}.default"
            dest_path = config_dir / filename

            data = tomllib.loads(src_path.read_text())
            data["production"] = new_section["production"]

            dest_path.write_text(tomli_w.dumps(data))
            dest_path.chmod(0o644)
            written.append(str(dest_path))

        return True, "Config files written:\n" + "\n".join(f"  {w}" for w in written)

    except OSError as exc:
        return False, f"Failed to write config: {exc}"
