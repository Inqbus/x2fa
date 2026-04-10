import os
from flask import Flask

from x2fa.config import cfg
from x2fa.helpers.attr_dict import AttrDict

def config(app: Flask):
    # Attach the config to the app
    for key in cfg:
        # casting the dynaconf instance into a dict prevents problems with dynaconf live updates.
        setattr(app.config, key, AttrDict(dict(cfg[key])))

    # Disable Authlib HTTPS requirement for development/testing
    if cfg.x2fa.TESTING:
        os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

    # Startup checks
    if 'SECRET_KEY' not in app.config.x2fa_security:
        raise RuntimeError("SECRET_KEY not set in secret_config.toml!")
    app.config['SECRET_KEY'] = app.config.x2fa_security.SECRET_KEY


    if not cfg.x2fa.TESTING and not "RATELIMIT_STORAGE_URI" in app.config.x2fa_ratelimit:
        raise RuntimeError(
            "REDIS_URL must be set in production (distributed rate-limiting) in ratelimit_config.toml."
        )

    # Derive X2FA_ORIGIN if not explicitly set
    if 'ORIGIN' not in app.config.x2fa:
        app.config.x2fa.ORIGIN = f"https://{app.config.x2fa.DOMAIN}"
