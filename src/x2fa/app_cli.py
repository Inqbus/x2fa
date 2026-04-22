"""X2FA Flask App-Factory for CLI (minimal extensions, partial configs)."""

from importlib.resources import files

from flask import Flask

from x2fa.init_app.babel import babel
from x2fa.init_app.config import configure
from x2fa.init_app.database import db
from x2fa.init_app.errors import errors
from x2fa.init_app.limiter import limiter
from x2fa.init_app.security import security


def create_app_cli() -> Flask:
    """Create minimal Flask app for CLI commands (no routes)."""
    app = Flask(__name__, template_folder=str(files("x2fa").joinpath("templates")))

    configure(app)
    db.init_app(app)
    babel(app)
    security(app)
    errors(app)
    limiter.init_app(app)

    # Register CLI commands
    from x2fa.cli import register_commands

    register_commands(app)

    # CLI mode: no routes loaded (we skip routes to work with partial configs)

    return app
