"""Tests for the startup config-file presence check in init_app/config.py."""

import os
from unittest.mock import MagicMock, patch

import pytest

from x2fa.helpers.config_pool import ConfigPool


def _make_pool(missing: dict, loaded: dict | None = None) -> ConfigPool:
    """Return a ConfigPool pre-populated with the given missing/loaded dicts."""
    pool = ConfigPool.__new__(ConfigPool)
    pool._missing = dict(missing)
    pool._loaded  = dict(loaded or {})
    return pool


def _call_config(pool, env: str = "production"):
    """Import and call config(app) with the given pool and ENV_FOR_DYNACONF."""
    from x2fa.init_app import config as config_mod
    app = MagicMock()
    app.config = {}
    with (
        patch.object(config_mod, "cfg", pool),
        patch.dict(os.environ, {"ENV_FOR_DYNACONF": env}, clear=False),
    ):
        config_mod.config(app)
    return app


# ── Missing-config detection ──────────────────────────────────────────────────

class TestMissingConfigDetection:
    def test_raises_runtime_error_when_config_missing_in_production(self):
        pool = _make_pool({"x2fa": "x2fa_config.toml"})
        with pytest.raises(RuntimeError, match="x2fa_config.toml"):
            _call_config(pool, env="production")

    def test_error_message_contains_installer_hint(self):
        pool = _make_pool({"x2fa": "x2fa_config.toml"})
        with pytest.raises(RuntimeError, match="python -m installer"):
            _call_config(pool, env="production")

    def test_lists_all_missing_files_in_error(self):
        pool = _make_pool({
            "x2fa":          "x2fa_config.toml",
            "x2fa_security": "security_config.toml",
        })
        with pytest.raises(RuntimeError) as exc_info:
            _call_config(pool, env="production")
        msg = str(exc_info.value)
        assert "x2fa_config.toml"     in msg
        assert "security_config.toml" in msg

    def test_no_error_when_all_configs_present(self):
        pool = _make_pool(missing={})
        _call_config(pool, env="production")  # must not raise

    def test_no_error_in_testing_environment_even_with_missing_files(self):
        pool = _make_pool({"x2fa": "x2fa_config.toml"})
        _call_config(pool, env="testing")  # must not raise

    def test_no_error_in_testing_environment_case_insensitive(self):
        pool = _make_pool({"x2fa": "x2fa_config.toml"})
        _call_config(pool, env="TESTING")  # must not raise

    def test_raises_for_development_environment(self):
        pool = _make_pool({"x2fa_security": "security_config.toml"})
        with pytest.raises(RuntimeError):
            _call_config(pool, env="development")
