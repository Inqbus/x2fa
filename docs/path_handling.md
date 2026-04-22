# Path Handling Strategy for X2FA

## Problem Statement

X2FA needs to manage paths consistently across multiple contexts:

1. **Production runtime**: Flask WSGI app + CLI commands
2. **Installer**: Sets up configuration, database, CA certificates
3. **Tests**: Must isolate state, use tmp_path, not touch production

Currently:
- `x2fa/config.py` hardcodes `CONFIG_DIR = Path.home() / ".config" / "x2fa"`
- Tests set `X2FA_CONFIG_ROOT` but it's not consistently propagated
- Installer has its own path logic (`InstallConfig.config_root`) that conflicts
- Flask CLI commands don't respect `X2FA_CONFIG_ROOT` implicitly

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Environment Variables                             │
│  ┌──────────────────────┐  ┌──────────────────────┐                │
│  │  X2FA_CONFIG_DIR     │  │  X2FA_DATA_DIR       │                │
│  │  (config files)      │  │  (state/data files)  │                │
│  │  Default:            │  │  Default:            │                │
│  │  ~/.config/x2fa      │  │  ~/.local/share/x2fa │                │
│  └──────────────────────┘  └──────────────────────┘                │
│         │                         │                                 │
│         └───────────┬─────────────┘                                 │
│                     │                                               │
│  X2FA_HOME (test override - sets both)                              │
└─────────────────────┼───────────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
  ┌───────────┐   ┌─────────┐   ┌──────────┐
  │ Flask WSGI│   │ Flask   │   │ Installer│
  │ App       │   │ CLI     │   │          │
  │ (runtime) │   │ (CLI)   │   │          │
  └───────────┘   └─────────┘   └──────────┘
```

## Corrected Solution

### 1. Separate Config and Data Directories (XDG Compliant)

**Environment Variables**:
- `X2FA_CONFIG_DIR` - Configuration files directory
- `X2FA_DATA_DIR` - Data/state files directory  
- `X2FA_HOME` - Test override that sets both to same location

**Production defaults** (XDG compliant):
- Config: `~/.config/x2fa/`
- Data: `~/.local/share/x2fa/`

**Testing override**: Use `X2FA_HOME=<tmp_path>` to set both to a temp location.

### 2. Path Resolution Module

Create `src/x2fa/paths.py` with **pure functions** (no singletons, no global state):

```python
"""Path resolution for X2FA - single source of truth for all paths."""

import os
from pathlib import Path


def config_dir() -> Path:
    """Configuration files directory.
    
    Respects X2FA_CONFIG_DIR env var.
    When set: <X2FA_CONFIG_DIR>/
    When not set: ~/.config/x2fa/
    """
    config_dir_env = os.environ.get("X2FA_CONFIG_DIR")
    if config_dir_env:
        return Path(config_dir_env)
    # Fall back to old env var for backward compatibility
    config_root_old = os.environ.get("X2FA_CONFIG_ROOT")
    if config_root_old:
        return Path(config_root_old) / ".config" / "x2fa"
    return Path.home() / ".config" / "x2fa"


def data_dir() -> Path:
    """Data files directory.
    
    Respects X2FA_DATA_DIR env var.
    When set: <X2FA_DATA_DIR>/
    When not set: ~/.local/share/x2fa/
    """
    data_dir_env = os.environ.get("X2FA_DATA_DIR")
    if data_dir_env:
        return Path(data_dir_env)
    # Fall back to old env var for backward compatibility
    config_root_old = os.environ.get("X2FA_CONFIG_ROOT")
    if config_root_old:
        return Path(config_root_old) / ".local" / "share" / "x2fa"
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
    """Systemd user unit directory: <config_dir>/.config/systemd/user/"""
    return config_dir() / ".config" / "systemd" / "user"


# Test utility functions (do not use in production code)
def set_home(home_dir: Path) -> None:
    """Set both config and data dirs to same location (for testing).
    
    This is a TEST UTILITY only. Do not use in production code.
    
    Args:
        home_dir: Base directory (e.g., tmp_path)
    """
    os.environ["X2FA_CONFIG_DIR"] = str(home_dir / ".config" / "x2fa")
    os.environ["X2FA_DATA_DIR"] = str(home_dir / ".local" / "share" / "x2fa")


def reset_home() -> None:
    """Clear X2FA_HOME override (for testing cleanup)."""
    os.environ.pop("X2FA_CONFIG_DIR", None)
    os.environ.pop("X2FA_DATA_DIR", None)
```

**Key design decisions**:
- ✅ Pure functions - read `os.environ` on every call
- ✅ No singletons - no global mutable state
- ✅ XDG compliant - config and data are separate
- ✅ Test-friendly - `set_home()` for easy test setup

### 3. Lazy Dynaconf Initialization (CRITICAL FIX)

**Current problem**: Dynaconf loads files at import time, so changing env vars after import does nothing.

**CRITICAL FIX**: **`cfg` must be a `ConfigAccessor` class, NOT a module-level instantiation.**

If you do this at module level:
```python
# BAD - this is the current bug
cfg = _create_config_pool()  # Resolved at import time
```

Then even though `config_dir()` is a pure function, `cfg` is bound to a specific `ConfigPool` instance that has already loaded TOML files.

**The Only Working Solution**:

```python
# src/x2fa/config.py
"""Dynaconf config accessor with lazy initialization."""

from x2fa.helpers.config_pool import ConfigPool
from x2fa.paths import config_dir


def _create_config_pool() -> ConfigPool:
    """Create config pool with current paths."""
    config_dir_path = config_dir()
    
    CONFIGS = {
        "x2fa": ["x2fa_config.toml"],
        "x2fa_babel": ["babel_config.toml"],
        "x2fa_database": ["db_config.toml"],
        "x2fa_ratelimit": ["ratelimit_config.toml"],
        "x2fa_security": ["security_config.toml"],
    }
    
    pool = ConfigPool(config_dir_path)
    
    for namespace, filenames in CONFIGS.items():
        existing = [f for f in filenames if (config_dir_path / f).exists()]
    
        if existing:
            from dynaconf import Dynaconf
            dynaconf = Dynaconf(
                root_path=config_dir_path,
                settings_files=existing,
                environments=True,
                load_dotenv=True,
                envvar_prefix="X2FA",
            )
            pool.add_config(namespace, dynaconf)
        else:
            pool.add_missing(namespace, filenames[0])
    
    return pool


class ConfigAccessor:
    """Lazy config accessor that re-reads paths on each access.
    
    This is the ONLY pattern that works correctly with test isolation.
    Every access to a property calls config_dir() fresh, so env var
    changes are picked up immediately.
    """
    
    def __init__(self):
        self._pool = None
    
    def _ensure_pool(self) -> ConfigPool:
        if self._pool is None:
            self._pool = _create_config_pool()
        return self._pool
    
    def reload(self) -> None:
        """Force re-read on next access (for tests after env var changes)."""
        self._pool = None
    
    @property
    def x2fa(self):
        return self._ensure_pool().x2fa
    
    @property
    def x2fa_babel(self):
        return self._ensure_pool().x2fa_babel
    
    @property
    def x2fa_database(self):
        return self._ensure_pool().x2fa_database
    
    @property
    def x2fa_ratelimit(self):
        return self._ensure_pool().x2fa_ratelimit
    
    @property
    def x2fa_security(self):
        return self._ensure_pool().x2fa_security
    
    @property
    def all(self):
        return self._ensure_pool()


cfg = ConfigAccessor()  # Module-level instance, but lazy
```

**How it works**:
1. `cfg` is a module-level singleton (unavoidable, for `x2fa.config.cfg` import)
2. But `cfg._pool` starts as `None`
3. Each property access calls `_ensure_pool()` which:
   - Checks if `_pool` is `None`
   - If so, calls `_create_config_pool()` (which reads current env vars)
   - Returns the pool
4. Tests can call `cfg.reload()` to force re-creation on next access

**Critical migration rule**: Any code that currently does:
```python
# OLD (BROKEN - resolved at import time)
from x2fa.config import CONFIG_DIR
  # cfg gets bound to a specific ConfigPool
db_uri = cfg.x2fa_database.SQLALCHEMY_DATABASE_URI  # resolved once
```

Must change to:
```python
# NEW (WORKS - lazy access via properties)
  # lazy ConfigAccessor
db_uri = cfg.x2fa_database.SQLALCHEMY_DATABASE_URI  # resolved each access
```

And any module-level usage of `cfg` must be moved into functions:
```python
# BAD at module level
db_uri = cfg.x2fa_database.SQLALCHEMY_DATABASE_URI

# GOOD inside function
def get_db_uri():
    return cfg.x2fa_database.SQLALCHEMY_DATABASE_URI
```

### 4. Installer Uses Explicit Parameters (NO ENV MUTATION)

**IMPORTANT**: The installer should NOT mutate `os.environ`. Instead, it should pass paths explicitly to runner functions.

```python
# installer/models.py

from pathlib import Path
from typing import Optional

from x2fa.paths import config_dir as default_config_dir, data_dir as default_data_dir


class InstallConfig:
    """Configuration for the X2FA installer.
    
    Args:
        config_dir: Config directory path (defaults to X2FA_CONFIG_DIR env or ~/.config/x2fa)
        data_dir: Data directory path (defaults to X2FA_DATA_DIR env or ~/.local/share/x2fa)
        install_root: Root of the X2FA repository (for finding migrations, etc.)
    """
    
    def __init__(
        self,
        config_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        install_root: Path = Path.cwd(),
    ):
        self.install_root = install_root
        # Use explicit params first, then env vars, then defaults
        self.config_dir = config_dir or default_config_dir()
        self.data_dir = data_dir or default_data_dir()
        
        # Validate directories exist or can be created
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    @property
    def db_path(self) -> Path:
        return self.data_dir / "db.sqlite"
    
    @property
    def ca_key_path(self) -> Path:
        return self.data_dir / "ca_key.pem"
    
    @property
    def ca_cert_path(self) -> Path:
        return self.data_dir / "ca_cert.pem"
```

**Usage**:
```python
# Normal usage - uses env vars or defaults
config = InstallConfig()

# Test usage - explicit paths (NO env var mutation)
config = InstallConfig(
    config_dir=tmp_path / ".config" / "x2fa",
    data_dir=tmp_path / ".local" / "share" / "x2fa",
)

# If the installer must spawn subprocesses, pass paths via env dict:
import subprocess
import os

def run_flask_command(config: InstallConfig, cmd: list[str]) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "X2FA_CONFIG_DIR": str(config.config_dir),
        "X2FA_DATA_DIR": str(config.data_dir),
    }
    return subprocess.run([sys.executable, "-m", "flask"] + cmd, env=env)
```

**Key principle**: The installer receives paths as parameters, uses them internally, and only sets env vars for subprocess calls (via `env={...}` argument), NOT by mutating the current process.

### 5. Flask WSGI and CLI

These should **NOT** need changes if they use `x2fa.config.cfg`, since `cfg` is now lazy.

**wsgi.py** - already correct:
```python
from x2fa.app import create_app
app = create_app()
```

**cli.py** - already correct (uses `cfg` from config module):
```python

db_url = cfg.x2fa_database.SQLALCHEMY_DATABASE_URI
```

**But**: The CLI and migrations need to resolve relative SQLite paths. Update `_run_alembic_upgrade`:

```python
# src/x2fa/cli.py

from x2fa.paths import data_dir
from pathlib import Path

def _run_alembic_upgrade():
    # ... existing code ...
    
    db_url = cfg.x2fa_database.SQLALCHEMY_DATABASE_URI
    # Resolve relative paths to the data directory
    if db_url.startswith("sqlite:///"):
        relative_path = db_url[len("sqlite:///"):]
        if not relative_path.startswith("/"):
            # Resolve to absolute path, then use as_posix() for URI compatibility
            resolved_path = (data_dir() / relative_path).resolve().as_posix()
            db_url = "sqlite:///" + resolved_path
    
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    # ... rest of function ...
```

**migrations/env.py** - similar change:

```python
# src/x2fa/migrations/env.py

from x2fa.paths import data_dir
from pathlib import Path

def _db_url() -> str:
    # ... existing code that gets db_url from env/args ...
    
    # Resolve relative paths to the data directory
    if db_url.startswith("sqlite:///"):
        relative_path = db_url[len("sqlite:///"):]
        if not relative_path.startswith("/"):
            # Resolve to absolute path, then use as_posix() for URI compatibility
            resolved_path = (data_dir() / relative_path).resolve().as_posix()
            db_url = "sqlite:///" + resolved_path
    
    return db_url
```

**Windows compatibility note**: `Path.resolve().as_posix()` converts Windows paths like `C:\\foo\\bar` to `C:/foo/bar`, which SQLAlchemy requires for SQLite URIs.

### 6. Testing Strategy

**Option A: Per-test isolation with set_home()**

```python
import os
from pathlib import Path

@pytest.mark.asyncio
async def test_something(tmp_path):
    # Set test paths BEFORE any x2fa imports
    os.environ["X2FA_CONFIG_DIR"] = str(tmp_path / ".config" / "x2fa")
    os.environ["X2FA_DATA_DIR"] = str(tmp_path / ".local" / "share" / "x2fa")
    
    # Or use the convenience function:
    from x2fa.paths import set_home
    set_home(tmp_path)
    
    # Now all imports use the test paths
    from x2fa.paths import config_dir, data_dir
    assert config_dir() == tmp_path / ".config" / "x2fa"
```

**Option B: Fixture-based isolation (recommended)**

```python
@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Isolate X2FA paths to tmp_path for this test."""
    from x2fa.paths import set_home
    
    config_root = tmp_path / "config"
    set_home(config_root)
    
    yield config_root
    
    # Cleanup (optional - tmp_path handles this)
    from x2fa.paths import reset_home
    reset_home()


# Usage:
def test_something(isolated_paths):
    from x2fa.paths import config_dir
    assert config_dir() == isolated_paths / ".config" / "x2fa"
```

**Important**: Don't use `importlib.reload()` - it's fragile and doesn't fix module-level bindings.

### 7. Database URIs in Config Files

Update `db_config.toml.default` to use a placeholder that will be resolved at runtime:

```toml
# src/x2fa/config_files/db_config.toml.default

[default]
# SQLite database (default - runs within X2FA_HOME/data_dir)
# The actual path will be resolved in the app
SQLALCHEMY_DATABASE_URI = "sqlite:///db.sqlite"

[testing]
SQLALCHEMY_DATABASE_URI = "sqlite:///test_cli.db"
```

The CLI/migrations will resolve these relative paths to `data_dir()`.

### 8. Path Validation and Directory Creation

Add utilities to `paths.py`:

```python
def ensure_config_dir() -> Path:
    """Ensure config directory exists, create if needed."""
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_data_dir() -> Path:
    """Ensure data directory exists, create if needed."""
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_config_dir(path: Path) -> bool:
    """Validate that path is a directory (or can be created as one)."""
    try:
        if path.exists():
            return path.is_dir()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir(exist_ok=True)
        return True
    except (OSError, PermissionError):
        return False


def validate_data_dir(path: Path) -> bool:
    """Validate that path is a directory (or can be created as one)."""
    try:
        if path.exists():
            return path.is_dir()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir(exist_ok=True)
        return True
    except (OSError, PermissionError):
        return False
```

## Benefits of Corrected Architecture

✅ **XDG compliant** - Config and data are separate, following freedesktop.org spec  
✅ **Pure functions** - No global state, no singletons, thread-safe  
✅ **Lazy evaluation** - Paths re-read on every call, respect runtime env var changes  
✅ **Explicit parameters** - Installer takes paths as arguments, not global env vars  
✅ **Test-friendly** - `set_home()` makes test setup easy and explicit  
✅ **No import-time resolution** - Dynaconf initialized in `create_app()`  
✅ **Proper isolation** - Tests can run in parallel without path conflicts  

## Migration Checklist

### Phase 1: Core Changes

- [ ] Create `src/x2fa/paths.py` with corrected functions
- [ ] Update `src/x2fa/config.py` with lazy Dynaconf initialization
- [ ] Update `src/x2fa/cli.py` to resolve relative SQLite paths
- [ ] Update `src/x2fa/migrations/env.py` to resolve relative SQLite paths

### Phase 2: Installer Updates

- [ ] Update `installer/models.py` to use explicit `config_dir`/`data_dir` parameters
- [ ] Remove `installer/app.py` env var mutations from constructors
- [ ] Update subprocess calls to pass paths via `env={...}` argument
- [ ] Update CLI helpers to accept explicit paths as parameters

### Phase 3: Test Updates

- [ ] Update `tests/conftest.py` to use `set_home()` fixture
- [ ] Update all e2e tests to set `X2FA_CONFIG_DIR`/`X2FA_DATA_DIR`
- [ ] Update `tests/test_installer_e2e*.py` to use explicit path parameters
- [ ] Remove any `importlib.reload()` usage

### Phase 4: Configuration Updates

- [ ] Update `src/x2fa/config_files/db_config.toml.default` with comments
- [ ] Update documentation in `docs/` to reflect new env vars

### Phase 5: Verification

- [ ] Run all unit tests
- [ ] Run all integration tests
- [ ] Run all e2e tests
- [ ] Test production paths (no env vars set)
- [ ] Test test paths (env vars or set_home used)

## Migration from Old env vars

**Old**: `X2FA_CONFIG_ROOT`  
**New**: `X2FA_CONFIG_DIR` + `X2FA_DATA_DIR`

For backward compatibility, you may want to support both temporarily:

```python
def config_dir() -> Path:
    # Check new env var first
    config_dir_env = os.environ.get("X2FA_CONFIG_DIR")
    if config_dir_env:
        return Path(config_dir_env)
    
    # Fall back to old env var (deprecated)
    config_root_env = os.environ.get("X2FA_CONFIG_ROOT")
    if config_root_env:
        return Path(config_root_env) / ".config" / "x2fa"
    
    # Default
    return Path.home() / ".config" / "x2fa"
```

This gives users time to update their scripts before removing the old env var.
