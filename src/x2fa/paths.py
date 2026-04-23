"""Path resolution for X2FA - single source of truth for all paths."""

import os
from pathlib import Path


def get_home() -> Path:
    """Base directory for X2FA.
    
    Respects X2FA_HOME env var.
    When set: Path(X2FA_HOME)
    When not set: Path.home()
    """
    home_env = os.environ.get("X2FA_HOME")
    if home_env:
        return Path(home_env)
    return Path.home()


def config_dir() -> Path:
    """Configuration files directory.
    
    Respects X2FA_HOME env var.
    When set: <get_home()>/.config/x2fa/
    When not set: ~/.config/x2fa/
    """
    return get_home() / ".config" / "x2fa"


def data_dir() -> Path:
    """Data files directory.
    
    Respects X2FA_HOME env var.
    When set: <get_home()>/.local/share/x2fa/
    When not set: ~/.local/share/x2fa/
    """
    return get_home() / ".local" / "share" / "x2fa"


def client_cert_dir() -> Path:
    """Directory for client certificates: <data_dir>/"""
    return data_dir()


def systemd_user_dir() -> Path:
    """Systemd user unit directory: <config_dir>/.config/systemd/user/"""
    return config_dir() / ".config" / "systemd" / "user"


def db_path() -> Path:
    """Database file: <data_dir>/db.sqlite"""
    return data_dir() / "db.sqlite"


def ca_key_path() -> Path:
    """CA private key: <data_dir>/ca_key.pem"""
    return data_dir() / "ca_key.pem"


def ca_cert_path() -> Path:
    """CA certificate: <data_dir>/ca_cert.pem"""
    return data_dir() / "ca_cert.pem"


# Test utilities (do not use in production code)
def set_home(home_dir: Path) -> None:
    """Set X2FA_HOME for testing.
    
    This is a TEST UTILITY only. Do not use in production code.
    
    Args:
        home_dir: Base directory (e.g., tmp_path)
    """
    os.environ["X2FA_HOME"] = str(home_dir)


def reset_home() -> None:
    """Clear X2FA_HOME override (for testing cleanup)."""
    os.environ.pop("X2FA_HOME", None)
