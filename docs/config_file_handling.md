# X2FA Configuration File Handling

## Current Structure

Config files are stored in `src/x2fa/config_files/`:
- `x2fa_config.toml` - domain, origin, testing flag
- `db_config.toml` - database connection URI
- `ratelimit_config.toml` - rate limiting settings
- `security_config.toml` - secrets, session settings
- `babel_config.toml` - internationalization settings

Dynaconf loads these from the package directory via `config.py`.

## Problem with Installer

The installer currently writes runtime config files to `src/x2fa/config_files/`, overwriting the defaults. This:
1. Breaks Flask CLI commands (can't import app without valid config)
2. Requires re-installing the package to restore defaults
3. Mixes source code with runtime configuration
4. Not LSB-compliant for non-root users

## Proposed Architecture

### 1. External Config Directory (XDG compliant)

**Non-root user only (X2FA never runs as root):**
- Config: `~/.config/x2fa/`
- Data/CA: `~/.local/share/x2fa/`
- Database: `~/.local/share/x2fa/db.sqlite`

### 2. Template Files

Keep defaults in `src/x2fa/config_files/` as **read-only templates**:
- Use `.default` suffix or `.template` suffix
- Installer reads templates and writes to external directory

Example:
```
src/x2fa/config_files/x2fa_config.toml.default
src/x2fa/config_files/db_config.toml.default
src/x2fa/config_files/ratelimit_config.toml.default
src/x2fa/config_files/security_config.toml.default
```

### 3. Config Loading Strategy

Modify `config.py` to:

```python
from pathlib import Path

# XDG config directory (LSB compliant, non-root only)
CONFIG_DIR = Path.home() / ".config" / "x2fa"
CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)

# Check if runtime config exists, copy from templates if not
template_dir = Path(__file__).parent / "config_files"
if not any(CONFIG_DIR.glob("*.toml")):
    for template in template_dir.glob("*.toml.default"):
        dest = CONFIG_DIR / template.name.replace(".default", ".toml")
        dest.write_text(template.read_text())
        dest.chmod(0o644)

root_path = CONFIG_DIR
```

### 4. Installer Changes

The installer should:
1. Read templates from `src/x2fa/config_files/*.toml.default`
2. Fill in user values
3. Write to `~/.config/x2fa/` (non-root only, X2FA never runs as root)
4. NEVER overwrite files in `src/x2fa/config_files/`

### 5. File Ownership & Permissions

- Config dir (`~/.config/x2fa/`): current user, mode `0755`
- Config files: current user, mode `0644`
- CA private keys: current user, mode `0600` (keep offline)
- Data dir (`~/.local/share/x2fa/`): current user, mode `0700`

### 6. Backward Compatibility

Add migration path:
- Check for old `src/x2fa/config_files/` configs
- Warn user and offer to migrate

## Benefits

1. **Clean separation**: Source vs runtime config
2. **LSB compliant**: Uses standard locations
3. **Installer safe**: Can't break the source tree
4. **Multiple installations**: Different config dirs for different instances
5. **Package updates**: Source can be overwritten by package manager without losing config

## Implementation Status

✅ **Completed:**

1. ✅ Created template files (`*.toml.default`) in `src/x2fa/config_files/`
2. ✅ Updated `config.py` to load from `~/.config/x2fa/` and copy templates if needed
3. ✅ Updated `config_writer.py` to write to `~/.config/x2fa/`
4. ✅ Flask CLI commands now work correctly
5. ✅ Config files are created with proper permissions (0644)

**Remaining:**

- Update `db_config.toml.default` to use correct path placeholder
- Update installer to set correct absolute database path based on X2FA_DB_PATH env var
- Handle CA keys/certs in `~/.local/share/x2fa/` instead of source tree
