"""Thin wrappers around the X2FA flask CLI commands."""

import os
import subprocess
import sys
from pathlib import Path

# Maximum time a single flask CLI command is allowed to run.
# Longer-running commands (e.g. init-db on a slow disk) should increase this.
_FLASK_TIMEOUT = 120  # seconds


def _flask(args: list[str]) -> tuple[bool, str]:
    """Run `flask <args>` using the current Python interpreter.

    Uses sys.executable so the command always runs inside the same virtual
    environment as the installer — whether that is a development venv or a
    uv tool install. FLASK_APP uses the fully-qualified module path so it is
    resolvable from any working directory. The paths for config and data are
    determined by paths.py which respects X2FA_HOME.
    """
    from x2fa import paths

    env = {
        **os.environ,
        "FLASK_APP": "x2fa.wsgi_cli:app",
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "flask"] + args,
            cwd=paths.config_dir(),
            env=env,
            capture_output=True,
            text=True,
            timeout=_FLASK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {_FLASK_TIMEOUT}s"

    return result.returncode == 0, (result.stdout + result.stderr).strip()


def init_db() -> tuple[bool, str]:
    return _flask(["init-db"])


def init_keys() -> tuple[bool, str]:
    return _flask(["init-keys"])


def add_ca(name: str, cert_path: str) -> tuple[bool, str]:
    return _flask(["add-ca", name, cert_path])


def revoke_ca(name: str) -> tuple[bool, str]:
    return _flask(["revoke-ca", name])


def add_client(
    client_id: str,
    redirect_uri: str,
    method: str,
    jwks_uri: str | None = None,
    cert: str | None = None,
    secret: str | None = None,
) -> tuple[bool, str]:
    args = ["add-client", client_id, redirect_uri, "--method", method]
    if jwks_uri:
        args += ["--jwks-uri", jwks_uri]
    if cert:
        args += ["--cert", cert]
    if secret:
        args += ["--secret", secret]
    return _flask(args)


def list_cas() -> tuple[bool, str]:
    return _flask(["list-cas"])
