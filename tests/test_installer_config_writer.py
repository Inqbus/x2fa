"""Tests for installer/config_writer.py — verifies generated config file contents."""

import tomllib
from pathlib import Path

import pytest

from x2fa import paths
from installer.config_writer import write_configs
from installer.models import InstallConfig


def _config(**overrides) -> InstallConfig:
    cfg = InstallConfig(
        domain="test.example.com",
        secret_key="a" * 64,
        secret_salt="b" * 32,
        db_type="sqlite",
        use_redis=False,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _run(cfg: InstallConfig):
    return write_configs(cfg)


def _read(config_dir: Path, filename: str) -> dict:
    return tomllib.loads((config_dir / filename).read_text())


# ── Return value ──────────────────────────────────────────────────────────────

class TestReturnValue:
    def test_returns_true_on_success(self, isolated_paths):
        ok, _ = _run(_config())
        assert ok is True

    def test_message_lists_all_written_files(self, isolated_paths):
        _, msg = _run(_config())
        for name in ("security_config.toml", "x2fa_config.toml",
                     "db_config.toml", "ratelimit_config.toml"):
            assert name in msg

    def test_returns_false_on_unwritable_directory(self, isolated_paths):
        # Make config dir unwritable
        from x2fa import paths
        config_dir = paths.config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        config_dir.chmod(0o444)
        try:
            ok, msg = _run(_config())
            assert ok is False
            assert msg  # error message is non-empty
        finally:
            config_dir.chmod(0o755)


# ── File creation ─────────────────────────────────────────────────────────────

class TestFileCreation:
    def test_all_five_config_files_created(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        config_dir = paths.config_dir()
        for name in ("security_config.toml", "x2fa_config.toml",
                     "db_config.toml", "ratelimit_config.toml", "babel_config.toml"):
            assert (config_dir / name).exists(), f"missing: {name}"

    def test_config_directory_created(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        assert paths.config_dir().is_dir()


# ── security_config.toml ──────────────────────────────────────────────────────

class TestSecurityConfig:
    def test_secret_key_written(self, isolated_paths):
        _run(_config(secret_key="dead" * 16))
        from x2fa import paths
        prod = _read(paths.config_dir(), "security_config.toml")["production"]
        assert prod["SECRET_KEY"] == "dead" * 16

    def test_secret_salt_written(self, isolated_paths):
        _run(_config(secret_salt="beef" * 8))
        from x2fa import paths
        prod = _read(paths.config_dir(), "security_config.toml")["production"]
        assert prod["SECRET_SALT"] == "beef" * 8

    def test_session_cookie_secure_true(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        prod = _read(paths.config_dir(), "security_config.toml")["production"]
        assert prod["SESSION_COOKIE_SECURE"] is True

    def test_session_cookie_httponly_true(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        prod = _read(paths.config_dir(), "security_config.toml")["production"]
        assert prod["SESSION_COOKIE_HTTPONLY"] is True

    def test_session_cookie_samesite(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        prod = _read(paths.config_dir(), "security_config.toml")["production"]
        assert prod["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_session_lifetime(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        prod = _read(paths.config_dir(), "security_config.toml")["production"]
        assert prod["PERMANENT_SESSION_LIFETIME"] == 600

    def test_default_section_preserved_from_template(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        data = _read(paths.config_dir(), "security_config.toml")
        assert "default" in data
        assert "SECRET_KEY" in data["default"]

    def test_testing_section_preserved_from_template(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        data = _read(paths.config_dir(), "security_config.toml")
        assert "testing" in data


# ── x2fa_config.toml ──────────────────────────────────────────────────────────

class TestX2faConfig:
    def test_domain_written(self, isolated_paths):
        _run(_config(domain="2fa.myapp.io"))
        from x2fa import paths
        prod = _read(paths.config_dir(), "x2fa_config.toml")["production"]
        assert prod["DOMAIN"] == "2fa.myapp.io"

    def test_origin_derived_from_domain(self, isolated_paths):
        _run(_config(domain="2fa.myapp.io"))
        from x2fa import paths
        prod = _read(paths.config_dir(), "x2fa_config.toml")["production"]
        assert prod["ORIGIN"] == "https://2fa.myapp.io"

    def test_testing_false_in_production(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        prod = _read(paths.config_dir(), "x2fa_config.toml")["production"]
        assert prod["TESTING"] is False

    def test_default_section_preserved_from_template(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        data = _read(paths.config_dir(), "x2fa_config.toml")
        assert "default" in data


# ── db_config.toml ────────────────────────────────────────────────────────────

class TestDbConfig:
    def test_sqlite_default_path(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        uri = _read(paths.config_dir(), "db_config.toml")["production"]["SQLALCHEMY_DATABASE_URI"]
        assert uri.startswith("sqlite:///")
        assert "db.sqlite" in uri

    def test_custom_postgres_uri(self, isolated_paths):
        cfg = _config(db_type="postgres",
                      db_uri="postgresql://u:p@localhost/x2fa")
        _run(cfg)
        from x2fa import paths
        uri = _read(paths.config_dir(), "db_config.toml")["production"]["SQLALCHEMY_DATABASE_URI"]
        assert uri == "postgresql://u:p@localhost/x2fa"

    def test_default_section_preserved_from_template(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        data = _read(paths.config_dir(), "db_config.toml")
        assert "default" in data
        assert "SQLALCHEMY_DATABASE_URI" in data["default"]


# ── ratelimit_config.toml ─────────────────────────────────────────────────────

class TestRatelimitConfig:
    def test_memory_backend_without_redis(self, isolated_paths):
        _run(_config(use_redis=False))
        from x2fa import paths
        prod = _read(paths.config_dir(), "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_STORAGE_URI"] == "memory://"

    def test_redis_backend_when_enabled(self, isolated_paths):
        cfg = _config(use_redis=True, redis_uri="redis://localhost:6379/1")
        _run(cfg)
        from x2fa import paths
        prod = _read(paths.config_dir(), "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_STORAGE_URI"] == "redis://localhost:6379/1"

    def test_strategy_moving_window(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        prod = _read(paths.config_dir(), "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_STRATEGY"] == "moving-window"

    def test_headers_enabled(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        prod = _read(paths.config_dir(), "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_HEADERS_ENABLED"] is True

    def test_default_section_preserved_from_template(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        data = _read(paths.config_dir(), "ratelimit_config.toml")
        assert "default" in data


# ── babel_config.toml ─────────────────────────────────────────────────────────

class TestBabelConfig:
    def test_babel_config_copied(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        data = _read(paths.config_dir(), "babel_config.toml")
        assert "default" in data
        assert "BABEL_DEFAULT_LOCALE" in data["default"]

    def test_babel_config_has_no_production_section(self, isolated_paths):
        _run(_config())
        from x2fa import paths
        data = _read(paths.config_dir(), "babel_config.toml")
        assert "production" not in data
