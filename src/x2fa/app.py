"""X2FA Flask App-Factory."""
import os
from pathlib import Path

from flask import Flask

from x2fa.init_app.babel import babel
from x2fa.init_app.config import config
from x2fa.init_app.database import database
from x2fa.init_app.errors import errors
from x2fa.init_app.limiter import limiter
from x2fa.init_app.routes import routes
from x2fa.init_app.security import security


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=Path(__file__).parent/"templates"
    )

    config(app)
    database(app)
    babel(app)
    routes(app)
    security(app)
    errors(app)
    limiter.init_app(app)

    return app