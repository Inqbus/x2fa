"""Thin wrappers around the X2FA flask CLI commands."""

import os
import subprocess
from pathlib import Path

X2FA_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = X2FA_DIR / "src" / "x2fa"


def _flask(args: list[str], install_root: Path) -> tuple[bool, str]:
    """Run `uv run flask <args>` from src/x2fa directory.  Returns (success, output)."""
    env = {
        **os.environ,
        "FLASK_APP": "wsgi:app",
        "ENV_FOR_DYNACONF": "production",
    }
    result = subprocess.run(
        ["uv", "run", "flask"] + args,
        cwd=SRC_DIR,
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
) -> tuple[bool, str]:
    args = ["add-client", client_id, redirect_uri, "--method", method]
    if jwks_uri:
        args += ["--jwks-uri", jwks_uri]
    if cert:
        args += ["--cert", cert]
    return _flask(args, install_root)


def list_cas(install_root: Path) -> tuple[bool, str]:
    return _flask(["list-cas"], install_root)
