"""Path resolution for X2FA - single source of truth for all paths."""

import os
from pathlib import Path


def config_dir() -> Path:
    """Configuration files directory.
    
    Respects X2FA_CONFIG_ROOT env var for testing (which sets x2fa_home).
    When set: <X2FA_CONFIG_ROOT>/.config/x2fa/
    When not set: ~/.config/x2fa/
    """
    config_root_env = os.environ.get("X2FA_CONFIG_ROOT")
    if config_root_env:
        custom_config_root = Path(config_root_env)
        return custom_config_root / ".config" / "x2fa"
    return Path.home() / ".config" / "x2fa"


def data_dir() -> Path:
    """Data files directory.
    
    Respects X2FA_CONFIG_ROOT env var for testing (which sets x2fa_home).
    When set: <X2FA_CONFIG_ROOT>/.local/share/x2fa/
    When not set: ~/.local/share/x2fa/
    """
    config_root_env = os.environ.get("X2FA_CONFIG_ROOT")
    if config_root_env:
        custom_config_root = Path(config_root_env)
        return custom_config_root / ".local" / "share" / "x2fa"
    return Path.home() / ".local" / "share" / "x2fa"


def client_cert_dir() -> Path:
    """Directory for client certificates: <data_dir>/"""
    return data_dir()


def systemd_user_dir() -> Path:
    """Systemd user unit directory: <config_dir>/.config/systemd/user/"""
    return config_dir() / ".config" / "systemd" / "user"
