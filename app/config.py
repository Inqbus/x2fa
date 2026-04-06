import os
from datetime import timedelta
from dynaconf import Dynaconf

# Load configuration
settings = Dynaconf(
    settings_files=["settings.toml"],
    environments=True,
    load_dotenv=True,
    envvar_prefix="X2FA",
)


class Config:
    # Use Dynaconf settings
    SECRET_KEY = settings.SECRET_KEY
    X2FA_SECRET = settings.SECRET_KEY

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("X2FA_DATABASE_URL")
        or "sqlite:///x2fa.db"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    X2FA_DOMAIN = settings.DOMAIN
    X2FA_ORIGIN = (
        os.environ.get("X2FA_ORIGIN") or f"https://{settings.DOMAIN}"
    )  # defaults to https://<X2FA_DOMAIN> if unset

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=10)

    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL", "memory://")
    RATELIMIT_STRATEGY = "moving-window"  # prevents burst attacks at window boundaries
    RATELIMIT_HEADERS_ENABLED = True

    BABEL_DEFAULT_LOCALE = "de"
    BABEL_TRANSLATION_DIRECTORIES = "../translations"
    BABEL_SUPPORTED_LOCALES = [
        "de",
        "en",
        "fr",
        "es",
        "pt",
        "it",
        "nl",
        "pl",
        "ru",
        "zh",
        "ja",
        "ko",
        "ar",
        "tr",
        "sv",
        "cs",
        "hu",
    ]


class TestingConfig(Config):
    SECRET_KEY = "test-secret-key-not-for-production"
    X2FA_SECRET = "test-secret-key-not-for-production"
    TESTING = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = None
    RATELIMIT_STORAGE_URI = "memory://"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class E2ETestingConfig(TestingConfig):
    """Config for Playwright E2E tests.

    Uses StaticPool so that the fixture thread and the werkzeug server thread
    share the same in-memory SQLite connection (required for in-process tests).
    """

    from sqlalchemy.pool import StaticPool

    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }


class ProductionConfig(Config):
    # Redis is required in production for rate limiting across multiple workers
    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL")
