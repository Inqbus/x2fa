"""Path resolution for X2FA - single source of truth for all paths."""

import os
from pathlib import Path


def config_dir() -> Path:
    """Configuration files directory.
    
    Respects X2FA_CONFIG_ROOT env var for testing.
    When set to a custom path: <X2FA_CONFIG_ROOT>/.config/x2fa/
    When set to default XDG path or not set: ~/.config/x2fa/
    """
    config_root_env = os.environ.get("X2FA_CONFIG_ROOT")
    if config_root_env:
        custom_config_root = Path(config_root_env)
        # Check if the custom path is already the config dir (~/.config/x2fa)
        # If so, use it directly; otherwise append .config/x2fa
        default_config = Path.home() / ".config" / "x2fa"
        if custom_config_root == default_config:
            return custom_config_root
        return custom_config_root / ".config" / "x2fa"
    return Path.home() / ".config" / "x2fa"


def data_dir() -> Path:
    """Data files directory.
    
    Respects X2FA_CONFIG_ROOT env var for testing.
    When set to a custom path: <X2FA_CONFIG_ROOT>/.local/share/x2fa/
    When set to default XDG path or not set: ~/.local/share/x2fa/
    """
    config_root_env = os.environ.get("X2FA_CONFIG_ROOT")
    if config_root_env:
        custom_config_root = Path(config_root_env)
        # Check if the custom path is already the config dir (~/.config/x2fa)
        # If so, use the default data dir; otherwise use custom data dir
        default_config = Path.home() / ".config" / "x2fa"
        if custom_config_root == default_config:
            return Path.home() / ".local" / "share" / "x2fa"
        return custom_config_root / ".local" / "share" / "x2fa"
    return Path.home() / ".local" / "share" / "x2fa"


def db_path() -> Path:
    """Database file: <data_dir>/db.sqlite"""
    return data_dir() / "db.sqlite"


def ca_key_path() -> Path:
    """CA private key: <data_dir>/ca_key.pem"""
    return data_dir() / "ca_key.pem"


def ca_cert_path() -> Path:
    """CA certificate: <data_dir>/ca_cert.pem"""
    return data_dir() / "ca_cert.pem"


def client_cert_dir() -> Path:
    """Directory for client certificates: <data_dir>/"""
    return data_dir()


def systemd_user_dir() -> Path:
    """Systemd user unit directory."""
    config_dir_env = os.environ.get("X2FA_CONFIG_ROOT")
    if config_dir_env:
        custom_config_root = Path(config_dir_env)
        default_config = Path.home() / ".config" / "x2fa"
        if custom_config_root == default_config:
            return default_config / ".config" / "systemd" / "user"
        return custom_config_root / ".config" / "systemd" / "user"
    return Path.home() / ".config" / "x2fa" / ".config" / "systemd" / "user"
