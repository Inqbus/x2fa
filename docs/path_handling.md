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
│                    X2FA_CONFIG_ROOT (env var)                        │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  Controls both config and data directories                    │  │
│  │  Config: <X2FA_CONFIG_ROOT>/.config/x2fa/                     │  │
│  │  Data:   <X2FA_CONFIG_ROOT>/.local/share/x2fa/                │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
  ┌───────────┐         ┌─────────┐           ┌──────────┐
  │ Flask WSGI│         │ Flask   │           │ Installer│
  │ App       │         │ CLI     │           │          │
  │ (runtime) │         │ (CLI)   │           │          │
  └───────────┘         └─────────┘           └──────────┘
```

## Solution

### 1. Single Source of Truth: `X2FA_CONFIG_ROOT`

**Environment Variable**: `X2FA_CONFIG_ROOT`

**Production default**: `~/.config/x2fa`

**Testing override**: `<tmp_path>/config` or set via `monkeypatch.setenv("X2FA_CONFIG_ROOT", str(tmp_path / "config"))`

### 2. Path Resolution Module

Create `src/x2fa/paths.py`:

```python
"""Path resolution for X2FA - single source of truth for all paths."""

import os
from pathlib import Path

# XDG-compliant base directories
# This is the ONLY place where default paths are hardcoded
_BASE_CONFIG = Path.home() / ".config" / "x2fa"


def config_root() -> Path:
    """Root directory for all X2FA configuration.
    
    Respects X2FA_CONFIG_ROOT env var for testing.
    """
    return Path(os.environ.get("X2FA_CONFIG_ROOT", _BASE_CONFIG))


def config_dir() -> Path:
    """Configuration files directory: <config_root>/.config/x2fa/"""
    return config_root() / ".config" / "x2fa"


def data_dir() -> Path:
    """Data files directory: <config_root>/.local/share/x2fa/"""
    return config_root() / ".local" / "share" / "x2fa"


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
```

Update `src/x2fa/config.py`:

```python
from x2fa.paths import config_dir

CONFIG_DIR = config_dir()  # Now reads from paths module
```

### 3. Installer Uses `X2FA_CONFIG_ROOT`

**Current problem**: Installer uses `config_root` parameter AND `install_root`

**Solution**: Installer ONLY sets `X2FA_CONFIG_ROOT`, then uses the same path resolution as Flask

```python
# installer app.py
class InstallerApp(App[None]):
    def __init__(self, config_root: Path | None = None) -> None:
        super().__init__()
        # Set env var for path resolution
        if config_root:
            os.environ["X2FA_CONFIG_ROOT"] = str(config_root)
        
        # Now both installer and imported modules use same paths
        self.config = InstallConfig.load_session(
            install_root=Path.cwd(),  # X2FA repo location
            # config_root is now implicit via X2FA_CONFIG_ROOT
        )
```

### 4. Flask WSGI and CLI

`wsgi.py` and `cli.py` should NOT need changes if they use `x2fa.config.cfg`
which now reads from `paths.py`.

### 5. Testing Strategy

**Option A: Per-test isolation with X2FA_CONFIG_ROOT**

```python
@pytest.mark.asyncio
async def test_something(tmp_path):
    config_root = tmp_path / "config"
    
    # Set early, BEFORE importing anything that uses paths
    os.environ["X2FA_CONFIG_ROOT"] = str(config_root)
    
    # Now all imports use the test path
    from x2fa.paths import config_dir, data_dir
    assert config_dir() == config_root / ".config" / "x2fa"
```

**Option B: Fixture-based isolation**

```python
@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Isolate X2FA paths to tmp_path for this test."""
    config_root = tmp_path / "config"
    monkeypatch.setenv("X2FA_CONFIG_ROOT", str(config_root))
    
    # Force re-import of paths module to pick up new env var
    import importlib
    import x2fa.paths
    importlib.reload(x2fa.paths)
    
    yield config_root
    
    # Cleanup after test (optional, tmp_path handles this)
```

### 6. The Hard Problem: Production vs Testing

**Production**: `X2FA_CONFIG_ROOT` not set → uses `~/.config/x2fa`

**Testing**: Must set `X2FA_CONFIG_ROOT` to temp DIR

**Problem 1**: pytest-xdist runs tests in parallel with separate processes.
- Each test must set its own `X2FA_CONFIG_ROOT`
- No shared state between workers

**Problem 2**: Some modules are imported at module level, before fixtures set env vars
- `test_installer_e2e_real_ca.py` imports `installer.app` at top
- `installer.app` imports `x2fa.config` at module level
- By the time fixture runs, paths are already resolved

**Solution**: 
1. All path resolution must be **lazy** (function call, not module-level constant)
2. OR use a **singleton class** that re-reads env var on each access

```python
# Final implementation in paths.py
class PathResolver:
    """Singleton that always reads current X2FA_CONFIG_ROOT."""
    
    def config_dir(self) -> Path:
        return self._config_root() / ".config" / "x2fa"
    
    def config_root(self) -> Path:
        root = os.environ.get("X2FA_CONFIG_ROOT")
        if root:
            return Path(root)
        return Path.home() / ".config" / "x2fa"
    
    _instance = None
    
    @classmethod
    def instance(cls) -> "PathResolver":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

# Module-level convenience functions
def config_dir() -> Path:
    return PathResolver.instance().config_dir()

def config_root() -> Path:
    return PathResolver.instance().config_root()
```

This way, even if modules import `config_dir()` at module level, they call it at runtime with current env.

## Implementation Steps

### Phase 1: Create `paths.py` and update `config.py`

1. Create `src/x2fa/paths.py` with `PathResolver` class
2. Update `src/x2fa/config.py` to use `paths.config_dir()`

### Phase 2: Update Installer

1. Remove `config_root` parameter from `InstallConfig`
2. Installer sets `X2FA_CONFIG_ROOT` before any operations
3. Use `paths.get_data_dir()`, `paths.get_config_dir()` in installer

### Phase 3: Update Tests

1. All e2e tests set `X2FA_CONFIG_ROOT` before app creation
2. Remove redundant `config_root` parameters from runner functions
3. Use `paths.get_data_dir()` in test assertions

### Phase 4: Verify

1. Unit tests: No path changes needed (use in-memory SQLite)
2. Integration tests: Set `X2FA_CONFIG_ROOT` via fixture
3. E2E tests: Set in test setup

## Benefits

✅ Single source of path truth
✅ Tests can set `X2FA_CONFIG_ROOT` once, everything respects it
✅ No hardcoded paths in multiple places
✅ Production and test use same path resolution logic
✅ Thread-safe via lazy evaluation

## Migration Checklist

- [ ] Create `src/x2fa/paths.py`
- [ ] Update `src/x2fa/config.py` to use paths module
- [ ] Update `src/x2fa/wsgi.py` if needed
- [ ] Update `src/x2fa/cli.py` if needed
- [ ] Update `src/x2fa/init_app/` modules
- [ ] Update `installer/` modules to use `os.environ["X2FA_CONFIG_ROOT"]`
- [ ] Remove `config_root` parameter from `InstallConfig`
- [ ] Update all tests to set `X2FA_CONFIG_ROOT`
- [ ] Run all tests to verify no path issues
