"""Integration tests for X2FA Flask CLI (init-db, init-keys, add-client, etc.)."""

import os
import subprocess
import sys
from pathlib import Path

from x2fa.model import OIDCClient, TrustedCA


def _run_cli_command(args: list[str], env: dict = None, cwd: Path = None) -> tuple[int, str]:
    """Run a flask CLI command via subprocess and return (exit_code, output)."""
    if env is None:
        env = os.environ.copy()
    
    # Set FLASK_APP to use the CLI entry point
    env["FLASK_APP"] = "x2fa.wsgi_cli:app"
    
    result = subprocess.run(
        [sys.executable, "-m", "flask"] + args,
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def test_cli_init_db(tmp_path):
    """Test flask init-db creates all tables."""
    db_uri = f"sqlite:///{tmp_path / 'test.db'}"
    env = os.environ.copy()
    env["FLASK_APP"] = "x2fa.wsgi_cli:app"
    env["X2FA_DATABASE__SQLALCHEMY_DATABASE_URI"] = db_uri
    
    exit_code, output = _run_cli_command(["init-db"], env=env)
    
    assert exit_code == 0, f"init-db failed: {output}"
    assert "Database tables created" in output


def test_cli_init_keys(tmp_path):
    """Test flask init-keys creates signing keys."""
    db_uri = f"sqlite:///{tmp_path / 'test.db'}"
    env = os.environ.copy()
    env["FLASK_APP"] = "x2fa.wsgi_cli:app"
    env["X2FA_DATABASE__SQLALCHEMY_DATABASE_URI"] = db_uri
    env["X2FA_SECRET_KEY"] = "test-secret-key-32-chars-minimum!"
    
    # Init DB first
    exit_code, _ = _run_cli_command(["init-db"], env=env)
    assert exit_code == 0
    
    # Then init-keys
    exit_code, output = _run_cli_command(["init-keys"], env=env)
    assert exit_code == 0, f"init-keys failed: {output}"
    assert "Signing key generated" in output
