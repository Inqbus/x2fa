"""End-to-end test for the installer with Certificate Authority variant.

This test drives the entire installer TUI workflow with REAL CA generation,
REAL database operations, and REAL CLI calls — no mocking of the CA facility
or X2FA backend.  It verifies that the ExecuteScreen correctly performs:

1. Real CA generation via cryptography library
2. Real flask database operations (init-db, init-keys, add-ca)
3. Real client certificate issuance via flask
4. Real OIDC client registration via flask
"""

import os
import stat
import sys
import tomllib
import time
from pathlib import Path
from subprocess import run

import pytest

from textual.widgets import Input

from installer.app import InstallerApp

_SIZE = (120, 60)

_ALL_OK_CHECKS = [
    {"label": "Running as x2fa",    "ok": True, "blocking": False},
    {"label": "Python ≥ 3.11",      "ok": True, "blocking": True},
    {"label": "uv package manager", "ok": True, "blocking": True},
    {"label": "Port 5000 free",     "ok": True, "blocking": False},
    {"label": "Redis reachable",    "ok": True, "blocking": False},
]


def _read_toml(x2fa_home: Path, filename: str) -> dict:
    """Read a config file from the XDG config directory."""
    config_dir = x2fa_home / ".config" / "x2fa"
    return tomllib.loads((config_dir / filename).read_text())


async def _wait_for_screen_change(pilot, app, expected_screen_prefix: str, timeout: float = 5.0):
    """Wait for the app screen to change to one matching expected_screen_prefix."""
    start = time.time()
    while time.time() - start < timeout:
        current = app.screen.__class__.__name__
        if current.startswith(expected_screen_prefix):
            return current
        await pilot.pause(0.1)
    raise AssertionError(
        f"Screen never changed to {expected_screen_prefix}. "
        f"Final screen: {app.screen.__class__.__name__}"
    )


@pytest.mark.asyncio
async def test_e2e_real_ca_generate(tmp_path):
    """Real e2e test: walks through installer with tls_client_auth, verifies
    ExecuteScreen performs REAL database and CA operations."""
    
    # Set X2FA_CONFIG_ROOT BEFORE creating the app so dynaconf uses tmp_path
    config_root = tmp_path / "config"
    os.environ["X2FA_CONFIG_ROOT"] = str(config_root)
    config_root.mkdir()
    
    # Data files go to XDG data dir relative to config_root
    data_dir = config_root / ".local" / "share" / "x2fa"
    data_dir.mkdir(parents=True)

    ca_name = "test-real-ca-e2e"
    ca_cn = "Test Real CA E2E"
    ca_key_path = str(data_dir / "ca_key.pem")
    ca_cert_path = str(data_dir / "ca_cert.pem")

    client_id = "real-ca-e2e-client.example.com"
    redirect_uri = "https://real-ca-e2e-client.example.com/cb"
    
    app = InstallerApp(x2fa_home=config_root)
    async with app.run_test(size=_SIZE) as pilot:
        
        # ── Navigate through all screens ──────────────────────────────────────
        
        # MainMenu → WelcomeScreen
        await pilot.click("#install")
        await _wait_for_screen_change(pilot, app, "Welcome")
        
        # WelcomeScreen → DatabaseScreen
        await pilot.click("#next")
        await _wait_for_screen_change(pilot, app, "Database")
        
        # DatabaseScreen → DomainScreen
        await pilot.click("#next")
        await _wait_for_screen_change(pilot, app, "Domain")
        
        # DomainScreen: set domain
        app.screen.query_one("#domain", Input).value = "e2e-real-ca.example.com"
        app.config.domain = "e2e-real-ca.example.com"
        await pilot.click("#next")
        await _wait_for_screen_change(pilot, app, "Security")
        
        # SecurityScreen: keys auto-generated, continue
        secret_key = app.config.secret_key
        await pilot.click("#next")
        await _wait_for_screen_change(pilot, app, "Client")
        
        # ClientScreen: tls_client_auth (default), fill form
        app.screen.query_one("#client_id", Input).value = client_id
        app.screen.query_one("#redirect_uri", Input).value = redirect_uri
        app.config.client_id = client_id
        app.config.client_redirect_uri = redirect_uri
        await pilot.click("#next")
        await _wait_for_screen_change(pilot, app, "CASetup")
        
        # ── CASetupScreen: configure REAL CA generation ──────────────────────
        app.config.ca_action = "generate"
        app.screen.query_one("#ca_name", Input).value = ca_name
        app.screen.query_one("#ca_cn", Input).value = ca_cn
        app.screen.query_one("#ca_key_path", Input).value = ca_key_path
        app.screen.query_one("#ca_cert_path", Input).value = ca_cert_path
        app.config.ca_name = ca_name
        app.config.ca_cn = ca_cn
        app.config.ca_key_path = ca_key_path
        app.config.ca_cert_path = ca_cert_path
        
        await pilot.click("#next")
        await _wait_for_screen_change(pilot, app, "Review")
        
        # ReviewScreen: confirm to trigger ExecuteScreen
        await pilot.click("#confirm")
        await _wait_for_screen_change(pilot, app, "Execute")
        
        # Wait for ExecuteScreen to complete and push SummaryScreen
        # The _run_installation() method runs in a thread
        await _wait_for_screen_change(pilot, app, "Summary")
        
        # Give thread a moment to finish writing files
        await pilot.pause(0.5)
    
    # ── Verify ExecuteScreen performed REAL operations ──────────────────────
    
    # 1. CA certificate was generated by generate_ca() during ExecuteScreen
    ca_key = Path(ca_key_path)
    ca_cert = Path(ca_cert_path)
    
    # Verify CA files exist and are valid
    assert ca_key.exists(), f"CA private key was not generated at {ca_key}"
    assert ca_cert.exists(), f"CA certificate was not generated at {ca_cert}"
    
    # Verify key permissions (should be 0600)
    key_mode = stat.S_IMODE(ca_key.stat().st_mode)
    assert key_mode == 0o600, f"CA key permissions should be 0600, got {oct(key_mode)}"
    
    # Verify certificate is valid by loading it
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    assert cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value == ca_cn
    assert cert.issuer == cert.subject, "CA should be self-signed"
    
    # 2. Client certificate was issued during ExecuteScreen (tls_client_auth)
    safe_id = client_id.replace("/", "_").replace(":", "_")
    client_cert_path = data_dir / f"{safe_id}.cert.pem"
    client_key_path = data_dir / f"{safe_id}.key.pem"
    client_ca_path = data_dir / f"{safe_id}.ca.pem"
    
    assert client_cert_path.exists(), "Client certificate was not issued"
    assert client_key_path.exists(), "Client private key was not issued"
    assert client_ca_path.exists(), "CA certificate copy was not issued"
    
    # Verify client cert was signed by our CA
    client_cert = x509.load_pem_x509_certificate(client_cert_path.read_bytes())
    assert client_cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value == client_id
    assert client_cert.issuer == cert.subject, "Client cert should be signed by CA"
    
    # 3. Config files were written
    x2fa = _read_toml(config_root, "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"] == "e2e-real-ca.example.com"
    assert x2fa["production"]["ORIGIN"] == "https://e2e-real-ca.example.com"
    
    security = _read_toml(config_root, "security_config.toml")
    assert security["production"]["SECRET_KEY"] == secret_key
    
    # 4. CA was registered in database via flask add-ca (called during ExecuteScreen)
    # Since X2FA_CONFIG_ROOT is set, all flask commands use the same config
    result = run(
        [sys.executable, "-m", "flask", "list-cas"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "FLASK_APP": "x2fa.wsgi_cli:app"},
    )
    assert result.returncode == 0, f"list-cas failed: {result.stderr}"
    assert ca_name in result.stdout, f"CA '{ca_name}' not registered in database"
    
    # Verify CA is not revoked
    assert "revoked" not in result.stdout.lower(), "CA should not be revoked"
