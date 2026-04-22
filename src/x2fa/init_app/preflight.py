    #
    #
    # # Check rate limiter config if available
    # if (
    #     hasattr(cfg, "x2fa_ratelimit")
    #     and not app.config.x2fa_ratelimit.current_env == "testing"
    #     and "RATELIMIT_STORAGE_URI" not in app.config.x2fa_ratelimit
    # ):
    #     raise RuntimeError(
    #         "REDIS_URL must be set in production (distributed rate-limiting) in ratelimit_config.toml."
    #     )
