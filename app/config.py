import os
from datetime import timedelta


class Config:
    # Accept either FLASK_SECRET_KEY or X2FA_SECRET for backwards compatibility
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("X2FA_SECRET")
    X2FA_SECRET = os.environ.get("X2FA_SECRET") or os.environ.get("FLASK_SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("X2FA_DATABASE_URL")
        or "sqlite:///x2fa.db"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    X2FA_DOMAIN = os.environ.get("X2FA_DOMAIN", "localhost")
    X2FA_ORIGIN = os.environ.get("X2FA_ORIGIN")  # defaults to https://<X2FA_DOMAIN> if unset

    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=10)

    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL", "memory://")
    RATELIMIT_STRATEGY = "moving-window"  # prevents burst attacks at window boundaries
    RATELIMIT_HEADERS_ENABLED = True

    BABEL_DEFAULT_LOCALE = "de"
    BABEL_SUPPORTED_LOCALES = ["de", "en"]


class TestingConfig(Config):
    SECRET_KEY = "test-secret-key-not-for-production"
    X2FA_SECRET = "test-secret-key-not-for-production"
    TESTING = True
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = None
    RATELIMIT_STORAGE_URI = "memory://"
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class ProductionConfig(Config):
    # Redis is required in production for rate limiting across multiple workers
    RATELIMIT_STORAGE_URI = os.environ.get("REDIS_URL")
