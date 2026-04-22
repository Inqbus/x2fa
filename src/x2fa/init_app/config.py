from dynaconf import Dynaconf
from flask import Flask

from x2fa.helpers.config_pool import ConfigPool
from x2fa.paths import config_dir

CONFIGS = {
    "x2fa": ["x2fa_config.toml"],
    "x2fa_babel": ["babel_config.toml"],
    "x2fa_database": ["db_config.toml"],
    "x2fa_ratelimit": ["ratelimit_config.toml"],
    "x2fa_security": ["security_config.toml"],
}



def config(app: Flask):
    config_by_namespace = load_config()
    for namespace, config_files in CONFIGS.items():
        setattr(app.config, namespace, getattr(config_by_namespace, namespace))


def load_config():
    config_dir_path = config_dir()
    _pool = ConfigPool(config_dir_path)

    for namespace, config_files in CONFIGS.items():

        for config_file in config_files:
            if not (config_dir_path / config_file).exists():
                raise RuntimeError(
                    f"Missing configuration file: {config_file}.\n"
                    "Run `python -m installer` to generate the configuration files."
                )

        dynaconf = Dynaconf(
            root_path=config_dir_path,
            settings_files=config_files,
            environments=False,
            load_dotenv=False,
        )
        _pool.add_config(namespace, dynaconf)

    return _pool
