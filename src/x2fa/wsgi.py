#!/usr/bin/env python3
"""WSGI entry point for X2FA (gunicorn / flask run).

The WSGI spec requires a callable application object.
Gunicorn and Flask both accept ``x2fa.wsgi:app`` — here ``app`` is
a factory that creates a fresh Flask app on each call, which is the
correct pattern for multi-worker deployments.
"""

from x2fa.app import create_app

# WSGI entry point — gunicorn/flask look up this name.
# Creating a new app per worker avoids sharing state across processes.
app = create_app()

if __name__ == "__main__":
    app.run(host=app.config.x2fa["HOST"], port=app.config.x2fa["PORT"])