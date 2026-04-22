"""Tests for installer/config_writer.py — verifies generated config file contents."""

import tomllib
from pathlib import Path

import pytest

from installer.config_writer import write_configs
from installer.models import InstallConfig


def _config(tmp_path: Path, **overrides) -> InstallConfig:
    cfg = InstallConfig(
        install_root=tmp_path,
        x2fa_home=tmp_path,   # redirect all XDG paths into tmp_path
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


def _read(tmp_path: Path, filename: str) -> dict:
    return tomllib.loads((tmp_path / ".config" / "x2fa" / filename).read_text())


# ── Return value ──────────────────────────────────────────────────────────────

class TestReturnValue:
    def test_returns_true_on_success(self, tmp_path):
        ok, _ = _run(_config(tmp_path))
        assert ok is True

    def test_message_lists_all_written_files(self, tmp_path):
        _, msg = _run(_config(tmp_path))
        for name in ("security_config.toml", "x2fa_config.toml",
                     "db_config.toml", "ratelimit_config.toml"):
            assert name in msg

    def test_returns_false_on_unwritable_directory(self, tmp_path):
        # Make config dir unwritable
        config_dir = tmp_path / ".config" / "x2fa"
        config_dir.mkdir(parents=True)
        config_dir.chmod(0o444)
        try:
            ok, msg = _run(_config(tmp_path))
            assert ok is False
            assert msg  # error message is non-empty
        finally:
            config_dir.chmod(0o755)


# ── File creation ─────────────────────────────────────────────────────────────

class TestFileCreation:
    def test_all_five_config_files_created(self, tmp_path):
        _run(_config(tmp_path))
        config_dir = tmp_path / ".config" / "x2fa"
        for name in ("security_config.toml", "x2fa_config.toml",
                     "db_config.toml", "ratelimit_config.toml", "babel_config.toml"):
            assert (config_dir / name).exists(), f"missing: {name}"

    def test_config_directory_created(self, tmp_path):
        _run(_config(tmp_path))
        assert (tmp_path / ".config" / "x2fa").is_dir()


# ── security_config.toml ──────────────────────────────────────────────────────

class TestSecurityConfig:
    def test_secret_key_written(self, tmp_path):
        _run(_config(tmp_path, secret_key="dead" * 16))
        prod = _read(tmp_path, "security_config.toml")["production"]
        assert prod["SECRET_KEY"] == "dead" * 16

    def test_secret_salt_written(self, tmp_path):
        _run(_config(tmp_path, secret_salt="beef" * 8))
        prod = _read(tmp_path, "security_config.toml")["production"]
        assert prod["SECRET_SALT"] == "beef" * 8

    def test_session_cookie_secure_true(self, tmp_path):
        _run(_config(tmp_path))
        prod = _read(tmp_path, "security_config.toml")["production"]
        assert prod["SESSION_COOKIE_SECURE"] is True

    def test_session_cookie_httponly_true(self, tmp_path):
        _run(_config(tmp_path))
        prod = _read(tmp_path, "security_config.toml")["production"]
        assert prod["SESSION_COOKIE_HTTPONLY"] is True

    def test_session_cookie_samesite(self, tmp_path):
        _run(_config(tmp_path))
        prod = _read(tmp_path, "security_config.toml")["production"]
        assert prod["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_session_lifetime(self, tmp_path):
        _run(_config(tmp_path))
        prod = _read(tmp_path, "security_config.toml")["production"]
        assert prod["PERMANENT_SESSION_LIFETIME"] == 600

    def test_default_section_preserved_from_template(self, tmp_path):
        _run(_config(tmp_path))
        data = _read(tmp_path, "security_config.toml")
        assert "default" in data
        assert "SECRET_KEY" in data["default"]

    def test_testing_section_preserved_from_template(self, tmp_path):
        _run(_config(tmp_path))
        data = _read(tmp_path, "security_config.toml")
        assert "testing" in data


# ── x2fa_config.toml ──────────────────────────────────────────────────────────

class TestX2faConfig:
    def test_domain_written(self, tmp_path):
        _run(_config(tmp_path, domain="2fa.myapp.io"))
        prod = _read(tmp_path, "x2fa_config.toml")["production"]
        assert prod["DOMAIN"] == "2fa.myapp.io"

    def test_origin_derived_from_domain(self, tmp_path):
        _run(_config(tmp_path, domain="2fa.myapp.io"))
        prod = _read(tmp_path, "x2fa_config.toml")["production"]
        assert prod["ORIGIN"] == "https://2fa.myapp.io"

    def test_testing_false_in_production(self, tmp_path):
        _run(_config(tmp_path))
        prod = _read(tmp_path, "x2fa_config.toml")["production"]
        assert prod["TESTING"] is False

    def test_default_section_preserved_from_template(self, tmp_path):
        _run(_config(tmp_path))
        data = _read(tmp_path, "x2fa_config.toml")
        assert "default" in data


# ── db_config.toml ────────────────────────────────────────────────────────────

class TestDbConfig:
    def test_sqlite_default_path(self, tmp_path):
        _run(_config(tmp_path))
        uri = _read(tmp_path, "db_config.toml")["production"]["SQLALCHEMY_DATABASE_URI"]
        assert uri.startswith("sqlite:///")
        assert "db.sqlite" in uri

    def test_custom_postgres_uri(self, tmp_path):
        cfg = _config(tmp_path, db_type="postgres",
                      db_uri="postgresql://u:p@localhost/x2fa")
        _run(cfg)
        uri = _read(tmp_path, "db_config.toml")["production"]["SQLALCHEMY_DATABASE_URI"]
        assert uri == "postgresql://u:p@localhost/x2fa"

    def test_default_section_preserved_from_template(self, tmp_path):
        _run(_config(tmp_path))
        data = _read(tmp_path, "db_config.toml")
        assert "default" in data
        assert "SQLALCHEMY_DATABASE_URI" in data["default"]


# ── ratelimit_config.toml ─────────────────────────────────────────────────────

class TestRatelimitConfig:
    def test_memory_backend_without_redis(self, tmp_path):
        _run(_config(tmp_path, use_redis=False))
        prod = _read(tmp_path, "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_STORAGE_URI"] == "memory://"

    def test_redis_backend_when_enabled(self, tmp_path):
        cfg = _config(tmp_path, use_redis=True, redis_uri="redis://localhost:6379/1")
        _run(cfg)
        prod = _read(tmp_path, "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_STORAGE_URI"] == "redis://localhost:6379/1"

    def test_strategy_moving_window(self, tmp_path):
        _run(_config(tmp_path))
        prod = _read(tmp_path, "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_STRATEGY"] == "moving-window"

    def test_headers_enabled(self, tmp_path):
        _run(_config(tmp_path))
        prod = _read(tmp_path, "ratelimit_config.toml")["production"]
        assert prod["RATELIMIT_HEADERS_ENABLED"] is True

    def test_default_section_preserved_from_template(self, tmp_path):
        _run(_config(tmp_path))
        data = _read(tmp_path, "ratelimit_config.toml")
        assert "default" in data


# ── babel_config.toml ─────────────────────────────────────────────────────────

class TestBabelConfig:
    def test_babel_config_copied(self, tmp_path):
        _run(_config(tmp_path))
        data = _read(tmp_path, "babel_config.toml")
        assert "default" in data
        assert "BABEL_DEFAULT_LOCALE" in data["default"]

    def test_babel_config_has_no_production_section(self, tmp_path):
        _run(_config(tmp_path))
        data = _read(tmp_path, "babel_config.toml")
        assert "production" not in data
