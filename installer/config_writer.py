import os
import tomli_w
from pathlib import Path

from .models import InstallConfig


def write_configs(config: InstallConfig) -> tuple[bool, str]:
    """Write all TOML config files to XDG config directory. Returns (success, log_message)."""
    config_dir = Path.home() / ".config" / "x2fa"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

    template_dir = (
        Path(__file__).resolve().parent.parent / "src" / "x2fa" / "config_files"
    )

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
