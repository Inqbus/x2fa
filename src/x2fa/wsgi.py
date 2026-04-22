#!/usr/bin/env python3
"""WSGI entry point for X2FA (gunicorn / flask run)."""

from x2fa.app import create_app

app = create_app()

if __name__ == "__main__":
    

    app.run(host=app.config.x2fa["HOST"], port=app.config.x2fa["PORT"])
