# X2FA Configuration File Handling

## Current Structure

Config files were stored in `src/x2fa/config_files/`:
- `x2fa_config.toml` - domain, origin, testing flag
- `db_config.toml` - database connection URI
- `ratelimit_config.toml` - rate limiting settings
- `security_config.toml` - secrets, session settings
- `babel_config.toml` - internationalization settings

Dynaconf loaded all configs at import time via `config.py`, requiring all files to be valid.

## Problem with Installer

The installer previously wrote runtime config files to `src/x2fa/config_files/`, overwriting the defaults. This:
1. Broke Flask CLI commands (can't import app without valid config)
2. Required re-installing the package to restore defaults
3. Mixed source code with runtime configuration
4. Not LSB-compliant for non-root users

## Solution: ConfigPool Architecture

### Single Responsibility

Each config file is loaded **only when accessed**, not at import time:
- No circular dependency between Flask commands and config files
- Clear, early error when config file is missing

### ConfigPool Class

**Location:** `src/x2fa/helpers/config_pool.py`

```python
class ConfigPool:
    """Pool of loaded Dynaconf instances with tracking of missing configs."""
    
    def __init__(self, config_dir: Path):
        self._config_dir = config_dir
        self._loaded = {}  # namespace -> Dynaconf instance
        self._missing = {}  # namespace -> filename
    
    def add_config(self, namespace: str, dynaconf_instance: Dynaconf):
        """Add a successfully loaded Dynaconf instance."""
        self._loaded[namespace] = dynaconf_instance
    
    def add_missing(self, namespace: str, filename: str):
        """Track a missing config namespace."""
        self._missing[namespace] = filename
```

**Access behavior:**
```python
from x2fa.config import cfg

# Works - config file exists
cfg.x2fa_database.SQLALCHEMY_DATABASE_URI  # Returns: "sqlite:///..."

# Fails with clear error - config file missing
cfg.x2fa_ratelimit.RATELIMIT_AUTHORIZE
# => AttributeError: Config file 'ratelimit_config.toml' not found in ~/.config/x2fa.
#    Run the installer first to generate configuration files.
```

### XDG Config Directory (Non-root only)

**Non-root user only (X2FA never runs as root):**
- Config: `~/.config/x2fa/`
- Data/CA: `~/.local/share/x2fa/`
- Database: `~/.local/share/x2fa/db.sqlite`

### Template Files

Keep defaults in `src/x2fa/config_files/` as **read-only templates**:
- Use `.default` suffix (e.g., `db_config.toml.default`)
- **Template structure**: Only `[default]` and `[testing]` sections
- **Installer writes**: Complete `[production]` section via `tomli_w`
- NEVER overwrites files in `src/x2fa/config_files/`

### Installer Changes

The installer:
1. Copies all templates to `.toml` files
2. Uses `tomli_w` to add `[production]` section to each config
3. Writes configs to `~/.config/x2fa/`
4. CLI commands work with partial configs (missing configs raise clear errors)

### File Ownership & Permissions

- Config dir (`~/.config/x2fa/`): current user, mode `0755`
- Config files: current user, mode `0644`
- Data dir (`~/.local/share/x2fa/`): current user, mode `0700`

### Separate CLI Entry Point

**`wsgi_cli.py`** loads minimal app (no routes) for CLI commands:
- Needs only: db_config, security_config, x2fa_config
- Routes (and rate limiting) only loaded for full web app

**`wsgi.py`** loads full app for web server:
- Needs all 5 config files
- Registers blueprints and CLI commands

## Benefits

1. ✅ **Clear early errors** - which file is missing, why it matters
2. ✅ **LSB compliant** - XDG config location
3. ✅ **Installer safe** - can't break source tree
4. ✅ **Partial configs** - CLI works with minimal configs
5. ✅ **Clean separation** - source vs runtime config
6. ✅ **No performance penalty** - only access checked once

## Implementation Status

✅ **Completed:**

1. ✅ Created `ConfigPool` class (`src/x2fa/helpers/config_pool.py`)
2. ✅ Updated `config.py` to use `ConfigPool` instead of Dynaconf
3. ✅ Created template files (`*.toml.default`) in `src/x2fa/config_files/`
4. ✅ Updated `config_writer.py` to write to `~/.config/x2fa/` with `tomli_w`
5. ✅ Updated installer to add `[production]` section to configs
6. ✅ Created `app_cli.py` for minimal CLI app (no routes)
7. ✅ Created `wsgi_cli.py` entry point for CLI commands
8. ✅ Removed `.env` file handling
9. ✅ Clear error messages for missing config files

## Remaining

None. This configuration file handling architecture is complete.
