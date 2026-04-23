# Path Handling Strategy for X2FA

## Problem Statement

X2FA needs to manage paths consistently across multiple contexts:

1. **Production runtime**: Flask WSGI app + CLI commands
2. **Installer**: Sets up configuration, database, CA certificates
3. **Tests**: Must isolate state, use tmp_path, not touch production

Currently:
- Tests use `X2FA_CONFIG_ROOT` and `--x2fa-home` CLI argument but these are being replaced by `X2FA_HOME`
- Both app and installer use `paths.py` to get paths from `X2FA_HOME`

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Environment Variables                             │
│                                                                       │
│  X2FA_HOME                                                            │
│  └─ Default: Path.home() (config in ~/.config/x2fa/)                 │
│  └─ Test override: <tmp_path> (isolate test runs)                    │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
                         │
               ┌─────────┼───────────┐
               │         │           │
               ▼         ▼           ▼
         ┌───────────┐ ┌─────────┐ ┌──────────┐
         │ Flask     │ │ Flask   │ │ Installer│
         │ WSGI App  │ │ CLI     │ │          │
         │ (runtime) │ │         │ │          │
         └───────────┘ └─────────┘ └──────────┘
         Both use paths.py functions
```

## Solution: Single Environment Variable `X2FA_HOME`

### 1. Path Resolution Module

`src/x2fa/paths.py` provides **pure functions** that construct all paths based on `X2FA_HOME`:

**Key design principle**: Eliminate code duplication with `get_home()` as single source of truth.

```python
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
```

**Key design decisions**:
- ✅ Single source of truth - `get_home()` checks `X2FA_HOME` once
- ✅ All functions delegate - `config_dir()`, `data_dir()`, etc. all use `get_home()`
- ✅ Pure functions - read `os.environ` on every call
- ✅ No singletons - no global mutable state
- ✅ Single env var - `X2FA_HOME` controls both config and data
- ✅ XDG compliant when not overridden (config + data separate)
- ✅ Test-friendly - `set_home()` for easy test setup

### 2. How It Works

**App and Installer**: Both use `paths.py` functions:
- Flask WSGI app: `config_dir()`, `data_dir()` from `paths.py`
- Flask CLI: `config_dir()`, `data_dir()` from `paths.py`
- Installer: `config_dir()`, `data_dir()` from `paths.py` (in `write_configs()`, etc.)
- Tests: Call `set_home(tmp_path)` to isolate runs

**No duplicate path logic**: Remove all path-related fields (`install_root`, `x2fa_home`) from `InstallConfig`. The installer only holds user choices (domain, CA CN, auth method). Paths are derived on-the-fly via `paths.py`.

**Systemd unit**: Does NOT need `WorkingDirectory` since x2fa loads config from `paths.py`. The service can run from any directory.

### 3. Migration Tasks

#### Update `src/x2fa/paths.py`

- [x] Replace `X2FA_CONFIG_ROOT` with `X2FA_HOME` (no backward compatibility)
- [x] Introduce `get_home()` as single source of truth
- [x] Update `config_dir()` to use `get_home()`
- [x] Update `data_dir()` to use `get_home()`
- [x] Remove duplicate env var checking (each function should delegate to `get_home()`)
- [x] Remove `_home_dir()` - replace with `get_home()`
- [x] Add test utilities: `set_home()` and `reset_home()`
- [x] Add helper functions: `db_path()`, `ca_key_path()`, `ca_cert_path()`

#### Update `installer/runner.py`

- [x] Remove `install_root` parameter (no longer needed)
- [x] Remove `x2fa_home` parameter - use `paths.py` for all paths

#### Update `installer/models.py`

- [x] Remove `InstallConfig.install_root` field
- [x] Remove `InstallConfig.x2fa_home` field
- [x] Remove `_data_dir()` and `_config_dir()` methods
- [x] Update all path uses in `InstallConfig` to use `paths.py` functions

#### Update `installer/app.py`

- [x] Remove `x2fa_home` parameter from `__init__()`
- [x] Update `load_session()` to not pass `install_root`/`x2fa_home`

#### Update `installer/__main__.py`

- [x] Remove `--x2fa-home` CLI argument
- [x] Update to not pass `x2fa_home` to app

#### Update `installer/screens/`

- [x] `ca_manage.py`: Remove `x2fa_home` and `install_root` references
- [x] `execute.py`: Remove `x2fa_home` and `install_root` references
- [x] `summary.py`: Use `paths.systemd_user_dir()` instead of `cfg.x2fa_home`
- [x] `welcome.py`: Use `paths.get_home()` in `_run_checks()`

#### Update `installer/config_writer.py`

- [x] Remove `WorkingDirectory={install_root}` from systemd unit template

#### Update `AGENTS.md`

- [x] Replace `X2FA_CONFIG_ROOT` with `X2FA_HOME`
- [x] Remove `X2FA_HOME` CLI argument documentation
- [x] Update testing guidelines to use `set_home()` instead of env var mutations
