# Testing the X2FA Installer

**Status:** Proposal  
**Date:** 2026-04-16  

---

## 1. Architecture Overview

The installer consists of four distinct layers that should be tested separately:

| Layer | File | Purpose | Recommended Test Type |
|-------|------|---------|----------------------|
| **App** | `installer/app.py` | Textual app routing, screen management | Unit (pytest-textual) |
| **Models** | `installer/models.py` | Dataclasses, path logic | Unit (pytest) |
| **Config Writer** | `installer/config_writer.py` | TOML generation, file IO | Unit (pytest, mocked IO) |
| **Runner** | `installer/runner.py` | Flask CLI subprocess calls | Unit (pytest, mocked subprocess) |
| **Screens** | `installer/screens/*.py` | Form validation, user input | Unit (pytest-textual) |

---

## 2. Test Strategy

### 2.1 Unit Tests (pytest)

**Target:** `installer/models.py`, `installer/config_writer.py`, `installer/runner.py`

**Fixtures needed:**

```python
# tests/conftest.py (installer-specific)

@pytest.fixture
def temp_config_dir(tmp_path):
    """Mock XDG config directory."""
    config_dir = tmp_path / ".config" / "x2fa"
    config_dir.mkdir(parents=True)
    return config_dir

@pytest.fixture
def mock_flask_success monkeypatch):
    """Mock successful flask subprocess call."""
    def mock_run(*args, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "OK"
        result.stderr = ""
        return result
    monkeypatch.setattr("subprocess.run", mock_run)

@pytest.fixture
def mock_flask_failure(monkeypatch):
    """Mock failed flask subprocess call."""
    def mock_run(*args, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "Error: Database not found"
        return result
    monkeypatch.setattr("subprocess.run", mock_run)
```

### 2.2 UI Tests (pytest-textual)

**Target:** `installer/screens/*.py`, `installer/app.py`

**Fixtures needed:**

```python
@pytest.fixture
def app():
    """Create installer app in test mode."""
    from installer.app import InstallerApp
    app = InstallerApp()
    app.headless = True
    return app

@pytest.fixture
def screen(app):
    """Compose and mount a screen for testing."""
    from installer.screens.welcome import WelcomeScreen
    app.push_screen(WelcomeScreen())
    yield app.screen
    app.pop_screen()
```

---

## 3. Test Cases

### 3.1 models.py Tests

| Test | Description |
|------|-------------|
| `test_install_config_defaults()` | Default paths are XDG-compliant (`~/.local/share/x2fa/`) |
| `test_install_config_db_uri()` | `effective_db_uri()` returns correct SQLite URI |
| `test_install_config_ca_paths()` | CA key/cert paths point to XDG data dir |
| `test_install_config_production_values()` | After user input, values are stored correctly |

### 3.2 config_writer.py Tests

| Test | Description |
|------|-------------|
| `test_write_configs_success()` | All 5 TOML files written with [production] section |
| `test_write_configs_babel_unchanged()` | babel_config.toml copied without modification |
| `test_write_configs_security()` | security_config.toml includes SECRET_KEY, SECRET_SALT |
| `test_write_configs_db()` | db_config.toml includes correct database URI |
| `test_write_configs_ratelimit()` | ratelimit_config.toml includes Redis or memory URI |
| `test_write_configs_permissions()` | Files created with mode 0644, dir with 0755 |
| `test_write_configs_os_error()` | Returns `(False, error_message)` on write failure |

### 3.3 runner.py Tests

| Test | Description |
|------|-------------|
| `test_flask_success()` | `_flask()` returns `(True, output)` on success |
| `test_flask_failure()` | `_flask()` returns `(False, output)` on failure |
| `test_init_db()` | Calls `uv run flask init-db` from `src/x2fa/` |
| `test_init_keys()` | Calls `uv run flask init-keys` |
| `test_add_ca()` | Calls `uv run flask add-ca` with name and cert path |
| `test_add_client_tls()` | Calls `uv run flask add-client` with `--method tls_client_auth` |
| `test_add_client_jwks()` | Calls `uv run flask add-client` with `--jwks-uri` |
| `test_env_flags()` | `FLASK_APP=wsgi:app`, `ENV_FOR_DYNACONF=production` in env |

### 3.4 Screens Tests (each screen)

For each screen (`welcome.py`, `database.py`, `domain.py`, `security.py`, `ca_setup.py`, `client.py`, `execute.py`, `summary.py`):

| Test | Description |
|------|-------------|
| `test_screen_compose()` | All widgets present and visible |
| `test_button_navigation()` | Button presses push correct screen |
| `test_validation_success()` | Valid input allows progression |
| `test_validation_error()` | Invalid input shows error message |
| `test_config_update()` | Input fields update `app.config` correctly |

**Example test:**

```python
def test_database_screen_validation_sqlite(screen):
    """DatabaseScreen accepts SQLite as valid option."""
    screen.query_one("#sqlite", Button).press()
    screen.query_one("#next").press()
    assert screen.app.config.db_type == "sqlite"
    assert "sqlite:///" in screen.app.config.effective_db_uri()

def test_domain_screen_validation_empty(screen):
    """DomainScreen rejects empty domain."""
    input_widget = screen.query_one("#domain_input", Input)
    input_widget.clear()
    screen.query_one("#next").press()
    assert screen.query_one(".error").visible
    assert app.config.domain == ""
```

### 3.5 App Tests

| Test | Description |
|------|-------------|
| `test_main_menu_shows()` | `MainMenuScreen` displays install/manage_ca/quit buttons |
| `test_install_button_pushes_welcome()` | Click install → `WelcomeScreen` shown |
| `test_ca_button_pushes_manage()` | Click manage CA → `CAManageScreen` shown |
| `test_quit_button_exits()` | Click quit → `app.exit()` called |

---

## 4. Mocking Strategy

### 4.1 Filesystem

```python
@pytest.fixture
def mock_templates(monkeypatch, tmp_path):
    """Mock template files in src/x2fa/config_files/."""
    template_dir = tmp_path / "src" / "x2fa" / "config_files"
    template_dir.mkdir(parents=True)
    
    # Create dummy template files
    for name in ["x2fa_config.toml", "db_config.toml", "security_config.toml",
                 "ratelimit_config.toml", "babel_config.toml"]:
        (template_dir / f"{name}.default").write_text("[default]\nkey=value\n")
    
    # Monkeypatch config_writer to use test template dir
    monkeypatch.setattr(
        "installer.config_writer.Path",
        lambda *a: template_dir.joinpath(*a)
    )
    return template_dir
```

### 4.2 Subprocess

```python
@pytest.fixture
def mock_uv_run(monkeypatch):
    """Mock `uv run flask` commands."""
    calls = []
    
    def mock_subprocess_run(cmd, cwd, env, capture_output, text):
        calls.append({"cmd": cmd, "cwd": str(cwd), "env": env})
        result = MagicMock()
        result.returncode = 0
        result.stdout = "OK"
        result.stderr = ""
        return result
    
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    return calls
```

---

## 5. Test File Structure

```
tests/
├── test_installer_models.py
├── test_installer_config_writer.py
├── test_installer_runner.py
├── test_installer_app.py
├── test_installer_screens.py
└── test_installer_integration.py (optional: end-to-end dry-run)
```

---

## 6. Example Test Files

### test_installer_runner.py

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from installer.runner import _flask, init_db, init_keys, add_ca, add_client

def test_flask_success():
    """_flask() returns (True, output) on success."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Database created"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        success, output = _flask(["init-db"], Path("."))
        assert success is True
        assert "Database created" in output

def test_flask_failure():
    """_flask() returns (False, output) on failure."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: FLASK_APP not set"
        mock_run.return_value = mock_result
        
        success, output = _flask(["init-db"], Path("."))
        assert success is False
        assert "Error" in output

def test_init_db():
    """init_db() calls correct command."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        success, output = init_db(Path("."))
        
        assert success is True
        args = mock_run.call_args
        assert "uv" in args.kwargs["args"][0]
        assert "flask" in args.kwargs["args"][1]
        assert "init-db" in args.kwargs["args"][2:]

def test_add_client_tls():
    """add_client() constructs correct CLI args for TLS method."""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "OK"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        success, output = add_client(
            "shop.example.com",
            "https://shop.example.com/callback",
            "tls_client_auth",
            Path("."),
        )
        
        args = mock_run.call_args
        assert "add-client" in args.kwargs["args"]
        assert "shop.example.com" in args.kwargs["args"]
        assert "--method" in args.kwargs["args"]
        assert "tls_client_auth" in args.kwargs["args"]
```

### test_installer_config_writer.py

```python
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from installer.config_writer import write_configs
from installer.models import InstallConfig

def test_write_configs_babel_unchanged(tmp_path, mock_templates):
    """babel_config.toml is copied without changes."""
    config = InstallConfig(
        domain="example.com",
        db_uri="sqlite:///test.db",
        secret_key="test_key",
        secret_salt="test_salt",
        ca_key_path=str(tmp_path / "ca_key.pem"),
        ca_cert_path=str(tmp_path / "ca_cert.pem"),
    )
    
    with patch("installer.config_writer.Path", lambda *a: tmp_path.joinpath(*a)):
        with patch("installer.config_writer.tomli_w.loads", return_value={"default": {}}):
            success, msg = write_configs(config)
    
    assert success is True
    assert (tmp_path / "babel_config.toml").exists()

def test_write_configs_security_includes_secrets(tmp_path, mock_templates):
    """security_config.toml includes SECRET_KEY and SECRET_SALT."""
    config = InstallConfig(
        domain="example.com",
        db_uri="sqlite:///test.db",
        secret_key="my_secret_key_123",
        secret_salt="my_salt_456",
        ca_key_path=str(tmp_path / "ca_key.pem"),
        ca_cert_path=str(tmp_path / "ca_cert.pem"),
    )
    
    with patch("installer.config_writer.Path", lambda *a: tmp_path.joinpath(*a)):
        with patch("installer.config_writer.tomli_w.loads", return_value={"default": {}}):
            success, msg = write_configs(config)
    
    assert success is True
    security_file = tmp_path / "security_config.toml"
    content = security_file.read_text()
    assert "my_secret_key_123" in content
    assert "my_salt_456" in content
```

---

## 7. Minimum Viable Test Suite

Start with these 10 critical tests:

1. ✅ `test_install_config_defaults` - validates XDG path structure  
2. ✅ `test_write_configs_success` - validates TOML generation  
3. ✅ `test_init_db` - validates Flask subprocess call  
4. ✅ `test_add_client_tls` - validates client registration  
5. ✅ `test_welcome_screen_shows_buttons` - validates UI structure  
6. ✅ `test_security_screen_generates_keys` - validates key generation  
7. ✅ `test_database_screen_accepts_sqlite` - validates user input  
8. ✅ `test_domain_screen_validates` - validates domain input  
9. ✅ `test_ca_setup_screen_default_ca_name` - validates CA config  
10. ✅ `test_execute_screen_runs_commands` - validates runner integration  

---

## 8. Future Enhancements

- **Selenium/Playwright tests** for full-user flow (requires Textual headless mode)
- **CI/CD integration** - run installer tests in GitHub Actions
- **Snapshot testing** for screen TUI rendering (textual-snapshot library)
