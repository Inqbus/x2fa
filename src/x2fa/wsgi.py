#!/usr/bin/env python3
"""WSGI entry point for X2FA (gunicorn / flask run)."""

import os

# Load .env file (before app creation)
if os.path.exists("../../.env"):
    with open("../../.env") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from app import create_app

app = create_app()

if __name__ == "__main__":
    from x2fa.config import x2fa
    app.run(host=x2fa['HOST'], port=x2fa['PORT'])
