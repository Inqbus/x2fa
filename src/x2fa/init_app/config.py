import os

from flask import Flask

from x2fa.config import cfg


def config(app: Flask):
    env = os.environ.get("ENV_FOR_DYNACONF", "production").lower()

    # Fail fast in non-testing environments when config files are absent.
    if env != "testing" and cfg._missing:
        missing = ", ".join(cfg._missing.values())
        raise RuntimeError(
            f"Missing configuration file(s): {missing}.\n"
            "Run `python -m installer` to generate the configuration files."
        )

    # Attach the config to the app
    # Only copy loaded configs (skip missing ones)
    for key in cfg._loaded:
        setattr(app.config, key, getattr(cfg, key))

    # Check rate limiter config if available
    if (
        hasattr(cfg, "x2fa_ratelimit")
        and not cfg.x2fa_ratelimit.current_env == "testing"
        and "RATELIMIT_STORAGE_URI" not in cfg.x2fa_ratelimit
    ):
        raise RuntimeError(
            "REDIS_URL must be set in production (distributed rate-limiting) in ratelimit_config.toml."
        )
