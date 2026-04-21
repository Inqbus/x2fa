# X2FA Agent Guidelines

## Project Overview
X2FA is a FIDO2 microservice with OIDC provider that handles two-factor authentication. It supports WebAuthn/FIDO2, TOTP, and backup codes. Client authentication uses X.509/mTLS and `private_key_jwt` — no shared secrets.

## Key Commands
- Run tests: `uv run pytest tests/ -v` (29 unit tests)
- Run single test: `uv run pytest tests/test_file.py::test_name -v`
- Start development server: `FLASK_APP=wsgi:app uv run flask run`
- Initialize database: `FLASK_APP=wsgi:app uv run flask init-db`
- Initialize keys: `FLASK_APP=wsgi:app uv run flask init-keys`
- Add client: `FLASK_APP=wsgi:app uv run flask add-client <client_id> <redirect_uri> [--method tls_client_auth|private_key_jwt]`
- Add CA: `FLASK_APP=wsgi:app uv run flask add-ca <name> <cert_path>`
- List CAs: `FLASK_APP=wsgi:app uv run flask list-cas`
- Revoke CA: `FLASK_APP=wsgi:app uv run flask revoke-ca <name>`
- Issue client cert: `FLASK_APP=wsgi:app uv run flask issue-client-cert <client_id> --ca <name>`
- Run demo RP: `cd demo_rp && uv run python app.py`
- Run installer TUI: `uv run --extra installer python -m installer`

## Environment Setup
- Requires Python 3.11+ and uv package manager
- `ENV_FOR_DYNACONF=production` for production
- `ENV_FOR_DYNACONF=testing` for testing
- Config is loaded via **Dynaconf** from `src/x2fa/config_files/*.toml` and environment variables (prefix `X2FA_`)
- X2FA will never be run as root. A special non-privileged user (e.g. `x2fa`) will be used.

## Architecture
- Flask-based web application with factory pattern (`create_app()` in `src/x2fa/app.py`)
- SQLAlchemy ORM for database (SQLite default, supports PostgreSQL/MySQL via extras)
- Redis required for distributed rate limiting in production
- OIDC Authorization Code flow with PKCE S256 (mandatory, `plain` rejected)
- FIDO2/WebAuthn support via py_webauthn 2.x (`src/x2fa/helpers/webauthn_helpers.py`)
- TOTP support via pyotp (`src/x2fa/helpers/totp_helpers.py`)
- Session-based state management (OIDC params not in URLs)
- ES256 ID tokens with public key verification (JWKS endpoint at `/.well-known/jwks.json`)

## Directory Structure
```
x2fa/
├── src/x2fa/
│   ├── app.py              # create_app() factory
│   ├── config.py           # Dynaconf configuration (cfg object)
│   ├── config_files/       # *.toml config files (x2fa_config, ratelimit, security, etc.)
│   ├── model/              # SQLAlchemy models (Credential, TOTPSecret, BackupCode, OIDCClient, TrustedCA, …)
│   ├── constants.py        # Sentinels (NEVER_USED), action/method strings
│   ├── cli.py              # Flask CLI commands
│   ├── wsgi.py             # WSGI entry point (loads .env, creates app)
│   ├── routes/             # Blueprints: auth, setup, verify, totp, backup
│   ├── oidc/               # Authlib OIDC server configuration
│   ├── services/           # Business logic (crypto, etc.)
│   ├── helpers/            # py_webauthn/pyotp wrappers
│   ├── init_app/           # Extension initialization (db, limiter, babel, security)
│   └── templates/          # Jinja2 templates
├── tests/
│   ├── conftest.py         # Unit test fixtures
│   └── test_*.py           # Unit tests
├── old_tests/              # Archived tests (pre-PKI, not yet updated)
├── demo_rp/                # Demo relying party for manual testing
└── .env                    # Local environment (git-ignored)
```

## Important Constraints
- **PKCE S256 enforced**: Code challenge method must be `S256`; `plain` is rejected
- **Nonces stored for 1 hour**: Even after use, to prevent replay of recently-issued ID tokens (60s expiry)
- **IP addresses never stored**: Audit log contains `SHA256(ip + X2FA_SECRET)` for GDPR compliance
- **Environment-specific config**: Dynaconf loads `[production]`, `[test]`, `[e2e]` sections from TOML files
- **Database sentinels**: `NEVER_USED` (1970-01-01) and `NEVER_EXPIRES` (9999-12-31) are timezone-naive
- **Babel i18n**: `ui_locales` OIDC parameter controls UI language (German default)

## Schema & Maintenance CLI
- Initialize schema: `uv run flask init-db` (creates all tables; no Alembic migrations)
- Cleanup old codes: `uv run flask cleanup-codes` (keep codes <1 hour for nonce protection)

---

## Reading Files
- **CRITICAL**: When reading files, always read the **COMPLETE** file content, never request partial snippets. Use the Read tool with full file access.
- Do not use `sed` to edit files. Always show diffs.

---

## Testing Guidelines

Ensure every AI-generated test is deterministic, isolated, fast, and maintainable.  
Applies to: pytest, pytest-asyncio, Textual TUI, Flask/SQLAlchemy, Dynaconf.

### 1. Core Principles

| Principle | Rule |
|-----------|------|
| **Isolation** | A test must not depend on another test's state, DB rows, files, or env vars. |
| **Determinism** | Same input → same output, always. No sleeps, no `time.time()`, no randomness without seeding. |
| **Speed tiers** | Unit < 50 ms. Integration < 2 s. E2E < 30 s. Never mix tiers in the same file without markers. |
| **Explicit over magic** | No hidden autouse fixtures that mutate global state. No `pytest` plugins that change semantics silently. |

### 2. Test Categories & Markers

```python
import pytest

@pytest.mark.unit          # Pure logic, no I/O, no DB, no event loop.
@pytest.mark.integration   # Real DB (transaction rollback), real subprocess, network to localhost.
@pytest.mark.e2e           # Full TUI walkthrough or CLI invocation. Must use tmp_path exclusively.
@pytest.mark.slow          # Anything > 2 s. CI can skip with `-m "not slow"`.
```

**File naming**
- `test_*.py` — unit / integration.
- `e2e_test_*.py` or `*_e2e_test.py` — end-to-end.
- Never put e2e and unit tests in the same file.

**Test structure**
- `tests/test_*.py` — unit tests (pytest fixtures in `tests/conftest.py`)
- `tests/e2e/test_*.py` — E2E tests (Textual TUI, installer workflow)
- `old_tests/e2e/test_*.py` — archived E2E tests (Playwright/Chromium, pre-PKI, not yet updated)

### 3. pytest & Async

#### 3.1 Event Loop & Parallelism
- `pytest-asyncio` and `anyio` run tests **sequentially by default**.
- If you see concurrency, the cause is `pytest-xdist` (`-n` flag), not async.
- **Never** add `asyncio` sleep loops hoping to "wait for parallel tasks". Poll state or use synchronization primitives.

#### 3.2 Async Fixtures
```python
@pytest.fixture
async def async_client():
    # OK: pytest-asyncio handles this
    async with AsyncClient() as c:
        yield c
```
- Do not create manual `asyncio.new_event_loop()` in fixtures.

#### 3.3 TUI Tests (Textual)
- Always use `app.run_test()` context manager.
- After clicking a widget that mutates the DOM (mounts/unmounts inputs), **pause**:
  ```python
  await pilot.click("#private_key_jwt")
  await pilot.pause()  # let reactive watchers finish
  app.screen.query_one("#jwks_uri", Input).value = "..."
  ```
- Wait for screen transitions by polling `app.screen.__class__.__name__`, not by fixed `sleep`.
- Assign `Input.value` directly only if the screen reads from `app.config` on `#next`. If the screen validates on `on_input_changed`, use `await pilot.press("a", "b", "c")`.

### 4. Database (SQLAlchemy / Flask-SQLAlchemy)

#### 4.1 Test DB Setup
- Use an in-memory SQLite URI for unit tests: `sqlite:///:memory:`.
- For integration tests with Postgres features, use `tmp_path` SQLite or a disposable Postgres DB per test worker.
- **Never** touch the development/production database.

#### 4.2 Transaction Rollback Pattern
```python
@pytest.fixture
def db_session(app):
    with app.app_context():
        connection = db.engine.connect()
        transaction = connection.begin()
        session = db.sessionmaker(bind=connection)()
        yield session
        transaction.rollback()
        connection.close()
```
- Tests must rollback. If a test intentionally commits, it must clean up in a `finally` block.

#### 4.3 Dynaconf in Tests
- Set `ENV_FOR_DYNACONF = "testing"` before app instantiation.
- Override paths to point into `tmp_path`:
  ```python
  monkeypatch.setenv("X2FA_CONFIG_ROOT", str(tmp_path / "config"))
  ```

### 5. Mocking Rules

#### 5.1 Patch Where Used, Not Where Defined
```python
# BAD: patches the definition module; caller may have imported directly.
patch("installer.ca.generate_ca")

# GOOD: patches the call site inside the screen or runner.
patch("installer.screens.ca_setup.generate_ca")
patch("installer.runner.generate_ca")
```

#### 5.2 Side-Effect Guards
When testing branches that must **not** call a function, use `side_effect=AssertionError`:
```python
patch("installer.ca.generate_ca",
      side_effect=AssertionError("generate_ca called in import mode"))
```
This produces a clear traceback if the guard is breached.

#### 5.3 Mock Return Values
- Return tuples for CLI-style runners: `(success: bool, message: str)`.
- Keep return values realistic; do not return `None` if the real code returns a dict.

### 6. File System & I/O

- Use `tmp_path` (pytest built-in) for all file output. No `/tmp`, no `Path.cwd()`.
- When testing file permissions, assert exact mode:
  ```python
  assert stat.S_IMODE(path.stat().st_mode) == 0o600
  ```
- Poll for file existence if written by a background thread; do not assume a fixed delay:
  ```python
  async def wait_for_file(path: Path, timeout: float = 5.0):
      for _ in range(int(timeout / 0.1)):
          if path.exists():
              return
          await asyncio.sleep(0.1)
      raise AssertionError(f"{path} never appeared")
  ```

### 7. Configuration & State

#### 7.1 App Config Objects
- If the app uses a dataclass/config object (`app.config`), mutate it **and** the widget state if the screen reads from widgets on submit. Prefer mutating the widget and letting reactive logic update `app.config`.
- If a screen requires `app.config.foo = "bar"` to enable a branch, set it explicitly. Do not rely on widget defaults that may change.

#### 7.2 Environment Variables
- Use `monkeypatch.setenv` / `monkeypatch.delenv`.
- Never mutate `os.environ` directly.

### 8. Assertions & Verification

- Assert on **data**, not on **implementation details** where possible.
- For TOML configs, parse with `tomllib` and assert key values; do not string-match.
- For certificates, load with `cryptography.x509` and assert subject/issuer attributes, not PEM substrings.

### 9. Anti-Patterns (Forbidden)

| Anti-Pattern | Why | Fix |
|--------------|-----|-----|
| `time.sleep()` in async tests | Flaky, slow | Poll state with timeout |
| `Path.cwd()` assumptions | Breaks in CI/IDE | Use `tmp_path` |
| `patch("module.define")` when caller uses `from module import define` | Mock never triggers | Patch the caller's namespace |
| Real DB without rollback | Test pollution | Transaction rollback fixture |
| `asyncio.get_event_loop().time()` mixed with `time.time()` | Clock skew | Use `time.time()` consistently or `pytest-asyncio` managed loop |
| E2E tests that call subprocess with default env | Picks up wrong config | Explicit `env=` with `X2FA_CONFIG_ROOT` |
| `await pilot.pause(0.5)` after thread work | Race condition | Poll for completion signal or file existence |

### 10. Example: Minimal Correct Async TUI Test

```python
import pytest
from textual.widgets import Input
from installer.app import InstallerApp

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_navigate_to_domain(tmp_path):
    app = InstallerApp(config_root=tmp_path)
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.click("#install")
        await pilot.pause()  # DOM settle

        # Type into input (triggers on_input_changed)
        await pilot.press("t", "e", "s", "t")
        await pilot.click("#next")

        # Wait for screen transition
        for _ in range(50):
            if app.screen.__class__.__name__ == "DomainScreen":
                break
            await pilot.pause(0.1)
        else:
            raise AssertionError("Screen did not change")

        assert app.config.domain == "test"
```

### 11. Review Checklist (Before Commit)

- [ ] Does the test pass when run alone (`pytest test_foo.py::test_bar`)?
- [ ] Does it pass when run with `-n auto` (xdist)?
- [ ] Does it leave files in `/tmp` or the repo?
- [ ] Are DB transactions rolled back?
- [ ] Are mocks patched at the call site?
- [ ] Are there any `sleep()` calls?
- [ ] Are env vars restored after the test?
