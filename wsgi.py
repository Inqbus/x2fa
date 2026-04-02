#!/usr/bin/env python3
"""WSGI entry point for X2FA (gunicorn / flask run)."""

import os

# Load .env file (before app creation)
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from app import create_app

config_name = os.environ.get("X2FA_ENV", "production")
app = create_app(config_name)

if __name__ == "__main__":
    host = os.environ.get("X2FA_HOST", "127.0.0.1")
    port = int(os.environ.get("X2FA_PORT", "5000"))
    app.run(host=host, port=port)
