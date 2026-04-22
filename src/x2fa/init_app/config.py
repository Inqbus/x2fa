import tomllib
from flask import Flask

from x2fa.helpers.attr_dict import AttrDict
from x2fa.helpers.config_pool import ConfigPool
from x2fa.paths import config_dir

CONFIGS = {
    "x2fa": "x2fa_config.toml",
    "x2fa_babel": "babel_config.toml",
    "x2fa_database": "db_config.toml",
    "x2fa_ratelimit": "ratelimit_config.toml",
    "x2fa_security": "security_config.toml",
}


def configure(app: Flask):
    config_by_namespace = load_config()
    for namespace, config_file_name in CONFIGS.items():
        setattr(app.config, namespace, getattr(config_by_namespace, namespace))


def load_config():
    config_dir_path = config_dir()
    _pool = ConfigPool(config_dir_path)

    for namespace, config_file_name in CONFIGS.items():

        config_file_path = config_dir_path / config_file_name
        if not config_file_path.exists():
            raise RuntimeError(
                f"Missing configuration file: {config_file_path}.\n"
                "Run `python -m installer` to generate the configuration files."
            )

        with open(config_file_path, "rb") as config_file:
            data = tomllib.load(config_file)

        # Use [production] section if available, otherwise [default]
        if "production" in data:
            section_data = data["production"]
        elif "default" in data:
            section_data = data["default"]
        else:
            section_data = {}

        attr_dict = AttrDict(section_data)
        _pool.add_config(namespace, attr_dict)

    return _pool
