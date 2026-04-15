"""X2FA Flask App-Factory."""

from pathlib import Path

from flask import Flask

from x2fa.init_app.babel import babel
from x2fa.init_app.config import config
from x2fa.init_app.database import db
from x2fa.init_app.errors import errors
from x2fa.init_app.limiter import limiter
from x2fa.init_app.routes import routes
from x2fa.init_app.security import security


def create_app() -> Flask:
    app = Flask(__name__, template_folder=Path(__file__).parent / "templates")

    config(app)
    db.init_app(app)
    babel(app)
    routes(app)
    security(app)
    errors(app)
    limiter.init_app(app)

    return app
