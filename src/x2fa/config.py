from pathlib import Path

from dynaconf import Dynaconf

from x2fa.helpers.attr_dict import AttrDict

root_path=Path(__file__).parent/'config_files'

cfg = AttrDict(
    x2fa = Dynaconf(
        root_path=root_path,
        settings_files=["x2fa_config.toml"],
        environments=True,
        load_dotenv=True,
        envvar_prefix="X2FA",
    ),
    x2fa_babel = Dynaconf(
        root_path=root_path,
        settings_files=["bable_config.toml"],
        environments=True,
        load_dotenv=True,
        envvar_prefix="X2FA_BABEL",
    ),
    x2fa_db = Dynaconf(
        root_path=root_path,
        settings_files=["db_config.toml"],
        environments=True,
        load_dotenv=True,
        envvar_prefix="X2FA_DB",
    ),
    x2fa_ratelimit = Dynaconf(
        root_path=root_path,
        settings_files=["ratelimit_config.toml"],
        environments=True,
        load_dotenv=True,
        envvar_prefix="X2FA_RATELIMIT",
    ),
    x2fa_security = Dynaconf(
        root_path=root_path,
        settings_files=["security_config.toml"],
        environments=True,
        load_dotenv=True,
        envvar_prefix="X2FA_SECURITY",
    )
)
