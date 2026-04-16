#!/usr/bin/env python3
"""WSGI entry point for X2FA CLI (flask commands)."""

from x2fa.app_cli import create_app_cli

app = create_app_cli()
