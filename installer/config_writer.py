import os
from pathlib import Path

from .models import InstallConfig


def write_configs(config: InstallConfig) -> tuple[bool, str]:
    """Write all TOML config files to XDG config directory. Returns (success, log_message)."""
    # XDG config directory (non-root only - X2FA never runs as root)
    config_dir = Path.home() / ".config" / "x2fa"

    # Create directory if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o755)

    written: list[str] = []
    try:
        storage = config.redis_uri if config.use_redis else "memory://"

        files = {
            "security_config.toml": (
                "[production]\n"
                f'SECRET_KEY  = "{config.secret_key}"\n'
                f'SECRET_SALT = "{config.secret_salt}"\n'
                "\nSESSION_COOKIE_SECURE   = true\n"
                "SESSION_COOKIE_HTTPONLY = true\n"
                'SESSION_COOKIE_SAMESITE = "Lax"\n'
                "PERMANENT_SESSION_LIFETIME = 600\n"
            ),
            "x2fa_config.toml": (
                "[production]\n"
                f'DOMAIN  = "{config.domain}"\n'
                f'ORIGIN  = "https://{config.domain}"\n'
                "TESTING = false\n"
            ),
            "db_config.toml": (
                "[default]\n"
                f'SQLALCHEMY_DATABASE_URI = "sqlite:///db.sqlite"\n'
                "\n"
                f"[production]\n"
                f'SQLALCHEMY_DATABASE_URI = "{config.effective_db_uri()}"\n'
            ),
            "ratelimit_config.toml": (
                "[production]\n"
                f'RATELIMIT_STORAGE_URI     = "{storage}"\n'
                'RATELIMIT_STRATEGY        = "moving-window"\n'
                "RATELIMIT_HEADERS_ENABLED = true\n"
            ),
        }

        for filename, content in files.items():
            path = config_dir / filename
            path.write_text(content)
            path.chmod(0o644)
            written.append(str(path))

        return True, "Config files written:\n" + "\n".join(f"  {w}" for w in written)

    except OSError as exc:
        return False, f"Failed to write config: {exc}"
