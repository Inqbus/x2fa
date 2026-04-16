from flask import Flask

from x2fa.config import cfg
from x2fa.helpers.attr_dict import AttrDict


def config(app: Flask):
    # Attach the config to the app
    for key in cfg:
        # casting the dynaconf instance into a dict prevents problems with dynaconf live updates.
        setattr(app.config, key, AttrDict(dict(cfg[key])))

    if (
        not cfg.x2fa.ENV_FOR_DYNACONF == "testing"
        and not "RATELIMIT_STORAGE_URI" in app.config.x2fa_ratelimit
    ):
        raise RuntimeError(
            "REDIS_URL must be set in production (distributed rate-limiting) in ratelimit_config.toml."
        )
