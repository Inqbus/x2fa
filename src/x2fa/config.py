from pathlib import Path

from dynaconf import Dynaconf

from x2fa.helpers.config_pool import ConfigPool

# XDG config directory (LSB compliant, non-root only)
CONFIG_DIR = Path.home() / ".config" / "x2fa"

CONFIGS = {
    "x2fa": ["x2fa_config.toml"],
    "x2fa_babel": ["babel_config.toml"],
    "x2fa_database": ["db_config.toml"],
    "x2fa_ratelimit": ["ratelimit_config.toml"],
    "x2fa_security": ["security_config.toml"],
}

pool = ConfigPool(CONFIG_DIR)

for namespace, filenames in CONFIGS.items():
    existing = [f for f in filenames if (CONFIG_DIR / f).exists()]

    if existing:
        dynaconf = Dynaconf(
            root_path=CONFIG_DIR,
            settings_files=existing,
            environments=True,
            load_dotenv=True,
            envvar_prefix="X2FA",
        )
        pool.add_config(namespace, dynaconf)
    else:
        pool.add_missing(namespace, filenames[0])

cfg = pool
