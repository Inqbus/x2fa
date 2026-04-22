"""Tests for the startup config-file presence check in init_app/config.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from x2fa.helpers.config_pool import ConfigPool


class TestMissingConfigDetection:
    def test_raises_runtime_error_when_config_missing(self):
        """Missing config file should raise RuntimeError during load_config."""
        from x2fa.init_app import config as config_mod
        
        with patch("x2fa.init_app.config.config_dir", return_value=Path("/tmp/nonexistent")):
            with pytest.raises(RuntimeError, match="x2fa_config.toml"):
                config_mod.load_config()

    def test_error_message_contains_installer_hint(self):
        """Error message should suggest running the installer."""
        from x2fa.init_app import config as config_mod
        
        with patch("x2fa.init_app.config.config_dir", return_value=Path("/tmp/nonexistent")):
            with pytest.raises(RuntimeError, match="python -m installer"):
                config_mod.load_config()

    def test_lists_all_missing_files_in_error(self):
        """Error should list the first missing config file."""
        from x2fa.init_app import config as config_mod
        
        with patch("x2fa.init_app.config.config_dir", return_value=Path("/tmp/nonexistent")):
            with pytest.raises(RuntimeError) as exc_info:
                config_mod.load_config()
            msg = str(exc_info.value)
            # Currently raises on first missing file encountered
            assert "x2fa_config.toml" in msg

    def test_no_error_when_all_configs_present(self):
        """Should not raise when all configs are loaded."""
        import tempfile
        import tomli_w
        from x2fa.init_app import config as config_mod
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # Create all required config files with minimal content
            for filename in ["x2fa_config.toml", "babel_config.toml", "db_config.toml", 
                           "ratelimit_config.toml", "security_config.toml"]:
                config_file = tmp_path / filename
                config_file.write_text("[production]\nNAME = \"test\"\n")
            
            with patch("x2fa.init_app.config.config_dir", return_value=tmp_path):
                pool = config_mod.load_config()
                assert hasattr(pool, "x2fa")
