#!/usr/bin/env python3
"""WSGI entry point for X2FA (gunicorn / flask run)."""

from x2fa.app import create_app

app = create_app()

if __name__ == "__main__":
    from x2fa.config import cfg

    app.run(host=cfg.x2fa["HOST"], port=cfg.x2fa["PORT"])
