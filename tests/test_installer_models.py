"""Tests for installer/models.py"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from installer.models import InstallConfig, _get_default_paths


class TestGetDefaultPaths:
    """Test _get_default_paths() XDG compliance."""

    def test_returns_tuple(self):
        """Returns 4-element tuple."""
        paths = _get_default_paths()
        assert isinstance(paths, tuple)
        assert len(paths) == 4

    def test_paths_are_strings(self):
        """All paths are strings."""
        paths = _get_default_paths()
        for p in paths:
            assert isinstance(p, str)

    def test_paths_contain_xdg_data(self):
        """Paths contain XDG data directory."""
        paths = _get_default_paths()
        for p in paths:
            assert ".local/share/x2fa" in p or ".config/x2fa" in p

    def test_paths_point_to_xdg_data(self):
        """Default ca_key, ca_cert, db point to ~/.local/share/x2fa/."""
        paths = _get_default_paths()
        ca_key, ca_cert, db, _ = paths
        
        assert "ca_key.pem" in ca_key
        assert "ca_cert.pem" in ca_cert
        assert "db.sqlite" in db
        assert ".local/share/x2fa" in ca_key
        assert ".local/share/x2fa" in ca_cert
        assert ".local/share/x2fa" in db


class TestInstallConfig:
    """Test InstallConfig dataclass."""

    def test_default_paths(self):
        """Defaults point to XDG directories."""
        config = InstallConfig()
        
        assert ".local/share/x2fa" in config.ca_key_path
        assert ".local/share/x2fa" in config.ca_cert_path
        assert config.db_type == "sqlite"
        assert config.proxy_type == "caddy"

    def test_effective_db_uri_sqlite(self):
        """effective_db_uri() returns correct SQLite path."""
        config = InstallConfig()
        uri = config.effective_db_uri()
        
        assert uri.startswith("sqlite:///")
        assert ".local/share/x2fa/db.sqlite" in uri

    def test_effective_db_uri_custom(self):
        """effective_db_uri() returns custom URI if set."""
        config = InstallConfig(db_uri="postgresql://user:pass@host/db")
        uri = config.effective_db_uri()
        
        assert uri == "postgresql://user:pass@host/db"

    def test_effective_ca_cert_generate(self):
        """effective_ca_cert() returns ca_cert_path for generate."""
        config = InstallConfig(ca_action="generate", ca_cert_path="/tmp/cert.pem")
        cert = config.effective_ca_cert()
        
        assert cert == "/tmp/cert.pem"

    def test_effective_ca_cert_import(self):
        """effective_ca_cert() returns ca_import_path for import."""
        config = InstallConfig(
            ca_action="import",
            ca_cert_path="/tmp/cert.pem",
            ca_import_path="/custom/ca.pem"
        )
        cert = config.effective_ca_cert()
        
        assert cert == "/custom/ca.pem"

    def test_install_root_defaults_to_cwd(self):
        """install_root defaults to current working directory."""
        config = InstallConfig()
        assert config.install_root == Path.cwd()

    def test_install_root_can_be_custom(self):
        """install_root can be set to custom path."""
        custom = Path("/custom/path")
        config = InstallConfig(install_root=custom)
        assert config.install_root == custom
