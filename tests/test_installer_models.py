"""Tests for installer/models.py"""

from pathlib import Path

import pytest

from installer.models import InstallConfig


class TestInstallConfigDefaults:
    def test_install_root_defaults_to_cwd(self):
        config = InstallConfig()
        assert config.install_root == Path.cwd()

    def test_config_root_defaults_to_home(self):
        config = InstallConfig()
        assert config.config_root == Path.home()

    def test_ca_key_path_derived_from_config_root(self, tmp_path):
        config = InstallConfig(config_root=tmp_path)
        assert config.ca_key_path == str(tmp_path / ".local" / "share" / "x2fa" / "ca_key.pem")

    def test_ca_cert_path_derived_from_config_root(self, tmp_path):
        config = InstallConfig(config_root=tmp_path)
        assert config.ca_cert_path == str(tmp_path / ".local" / "share" / "x2fa" / "ca_cert.pem")

    def test_ca_key_path_can_be_overridden(self, tmp_path):
        config = InstallConfig(config_root=tmp_path, ca_key_path="/custom/ca.key")
        assert config.ca_key_path == "/custom/ca.key"

    def test_ca_cert_path_can_be_overridden(self, tmp_path):
        config = InstallConfig(config_root=tmp_path, ca_cert_path="/custom/ca.crt")
        assert config.ca_cert_path == "/custom/ca.crt"

    def test_db_type_defaults_to_sqlite(self):
        assert InstallConfig().db_type == "sqlite"

    def test_proxy_type_defaults_to_caddy(self):
        assert InstallConfig().proxy_type == "caddy"


class TestDirectoryHelpers:
    def test_data_dir_under_config_root(self, tmp_path):
        config = InstallConfig(config_root=tmp_path)
        assert config._data_dir() == tmp_path / ".local" / "share" / "x2fa"

    def test_config_dir_under_config_root(self, tmp_path):
        config = InstallConfig(config_root=tmp_path)
        assert config._config_dir() == tmp_path / ".config" / "x2fa"

    def test_data_dir_default_points_into_home(self):
        config = InstallConfig()
        assert config._data_dir() == Path.home() / ".local" / "share" / "x2fa"

    def test_config_dir_default_points_into_home(self):
        config = InstallConfig()
        assert config._config_dir() == Path.home() / ".config" / "x2fa"


class TestEffectiveDbUri:
    def test_sqlite_default_uses_data_dir(self, tmp_path):
        config = InstallConfig(config_root=tmp_path)
        uri = config.effective_db_uri()
        assert uri.startswith("sqlite:///")
        assert str(tmp_path / ".local" / "share" / "x2fa" / "db.sqlite") in uri

    def test_custom_uri_returned_verbatim(self, tmp_path):
        config = InstallConfig(config_root=tmp_path, db_uri="postgresql://u:p@localhost/x2fa")
        assert config.effective_db_uri() == "postgresql://u:p@localhost/x2fa"


class TestEffectiveCaCert:
    def test_generate_returns_ca_cert_path_when_file_exists(self, tmp_path):
        cert = tmp_path / "cert.pem"
        cert.write_text("placeholder")
        config = InstallConfig(config_root=tmp_path, ca_action="generate",
                               ca_cert_path=str(cert))
        assert config.effective_ca_cert() == str(cert)

    def test_generate_returns_empty_when_file_missing(self, tmp_path):
        config = InstallConfig(config_root=tmp_path, ca_action="generate",
                               ca_cert_path=str(tmp_path / "nonexistent.pem"))
        assert config.effective_ca_cert() == ""

    def test_import_returns_ca_import_path_when_file_exists(self, tmp_path):
        cert = tmp_path / "ca.pem"
        cert.write_text("placeholder")
        config = InstallConfig(config_root=tmp_path, ca_action="import",
                               ca_import_path=str(cert))
        assert config.effective_ca_cert() == str(cert)

    def test_import_returns_empty_when_file_missing(self, tmp_path):
        config = InstallConfig(config_root=tmp_path, ca_action="import",
                               ca_import_path=str(tmp_path / "nonexistent.pem"))
        assert config.effective_ca_cert() == ""


class TestInstallRootOverride:
    def test_install_root_can_be_set(self, tmp_path):
        config = InstallConfig(install_root=tmp_path)
        assert config.install_root == tmp_path
