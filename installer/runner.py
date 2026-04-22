"""Thin wrappers around the X2FA flask CLI commands."""

import os
import subprocess
import sys
from pathlib import Path


def _flask(args: list[str], install_root: Path) -> tuple[bool, str]:
    """Run `flask <args>` using the current Python interpreter.

    Uses sys.executable so the command always runs inside the same virtual
    environment as the installer — whether that is a development venv or a
    uv tool install.  cwd is set to install_root (guaranteed to exist) and
    FLASK_APP uses the fully-qualified module path so it is resolvable from
    any working directory.
    """
    env = {
        **os.environ,
        "FLASK_APP": "x2fa.wsgi:app",
    }
    result = subprocess.run(
        [sys.executable, "-m", "flask"] + args,
        cwd=install_root,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def init_db(install_root: Path) -> tuple[bool, str]:
    return _flask(["init-db"], install_root)


def init_keys(install_root: Path) -> tuple[bool, str]:
    return _flask(["init-keys"], install_root)


def add_ca(name: str, cert_path: str, install_root: Path) -> tuple[bool, str]:
    return _flask(["add-ca", name, cert_path], install_root)


def revoke_ca(name: str, install_root: Path) -> tuple[bool, str]:
    return _flask(["revoke-ca", name], install_root)


def add_client(
    client_id: str,
    redirect_uri: str,
    method: str,
    install_root: Path,
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
    return _flask(args, install_root)


def list_cas(install_root: Path) -> tuple[bool, str]:
    return _flask(["list-cas"], install_root)
