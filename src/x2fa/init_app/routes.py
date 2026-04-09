from flask import Flask

# Register blueprints
from x2fa.routes.auth import auth_bp
from x2fa.routes.setup import setup_bp
from x2fa.routes.verify import verify_bp
from x2fa.routes.totp import totp_bp
from x2fa.routes.backup import backup_bp
# Register CLI commands
from x2fa.cli import register_commands


def routes(app : Flask):
    app.register_blueprint(auth_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(verify_bp)
    app.register_blueprint(totp_bp)
    app.register_blueprint(backup_bp)

    register_commands(app)
