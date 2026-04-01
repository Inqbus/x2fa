"""X2FA Flask App-Factory."""

import os
import secrets

from flask import Flask, g, render_template, request

from app.config import Config, ProductionConfig, TestingConfig
from app.extensions import db, limiter, migrate
from app.oidc import oauth
from app.oidc.grants import (
    S256OnlyCodeChallenge, X2FAAuthorizationCodeGrant, X2FAOpenIDCode,
    query_client, save_token,
)


def create_app(config_name: str = "production") -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
    )

    # Konfiguration laden
    _configs = {
        "production": ProductionConfig,
        "testing":    TestingConfig,
        "development": Config,
    }
    app.config.from_object(_configs.get(config_name, Config))

    # HTTPS-Pflicht in Authlib für Development/Testing deaktivieren
    if config_name in ("development", "testing"):
        import os as _os
        _os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

    # Startup-Checks
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "FLASK_SECRET_KEY oder X2FA_SECRET muss gesetzt sein!"
        )
    if config_name == "production" and not app.config.get("RATELIMIT_STORAGE_URI"):
        raise RuntimeError(
            "REDIS_URL muss in Production gesetzt sein (Distributed Rate-Limiting)."
        )

    # X2FA_ORIGIN ableiten wenn nicht explizit gesetzt
    if not app.config.get("X2FA_ORIGIN"):
        domain = app.config["X2FA_DOMAIN"]
        app.config["X2FA_ORIGIN"] = f"https://{domain}"

    # Extensions initialisieren
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # OIDC / Authlib
    oauth.init_app(app, query_client=query_client, save_token=save_token)
    oauth.register_grant(
        X2FAAuthorizationCodeGrant,
        [S256OnlyCodeChallenge(required=True), X2FAOpenIDCode(require_nonce=False)],
    )

    # WebAuthn initialisieren
    import webauthn_helpers
    webauthn_helpers.init_webauthn(app.config["X2FA_DOMAIN"])

    # Blueprints registrieren
    from app.routes.auth   import auth_bp
    from app.routes.setup  import setup_bp
    from app.routes.verify import verify_bp
    from app.routes.totp   import totp_bp
    from app.routes.backup import backup_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(verify_bp)
    app.register_blueprint(totp_bp)
    app.register_blueprint(backup_bp)

    # CLI-Befehle registrieren
    from app.cli import register_commands
    register_commands(app)

    # Datenbank-Tabellen anlegen (Development/Testing)
    if config_name in ("development", "testing"):
        with app.app_context():
            db.create_all()

    # Sicherheits-Header + CSP-Nonce
    @app.before_request
    def _set_nonce():
        g.nonce = secrets.token_urlsafe(16)

    @app.after_request
    def _security_headers(response):
        nonce = getattr(g, "nonce", "")
        # Content-Security-Policy mit per-Request-Nonce
        csp_parts = [
            "default-src 'none'",
            f"script-src 'nonce-{nonce}'",
            "style-src 'unsafe-inline'",
            "img-src data:",          # für TOTP-QR-Code
            "connect-src 'self'",
            "form-action 'self' https:",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
        response.headers["X-Frame-Options"]         = "DENY"
        response.headers["X-Content-Type-Options"]  = "nosniff"
        response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
        return response

    # Fehlerseiten
    @app.errorhandler(400)
    def _e400(err):
        return render_template("error.html",
                               status_code="400",
                               title="Ungültige Anfrage",
                               message=str(err.description)), 400

    @app.errorhandler(401)
    def _e401(err):
        return render_template("error.html",
                               status_code="401",
                               title="Nicht autorisiert",
                               message="Bitte melde dich erneut an."), 401

    @app.errorhandler(403)
    def _e403(err):
        return render_template("error.html",
                               status_code="403",
                               title="Zugriff verweigert",
                               message="Du hast keine Berechtigung für diese Seite."), 403

    @app.errorhandler(404)
    def _e404(err):
        return render_template("error.html",
                               status_code="404",
                               title="Nicht gefunden",
                               message="Die aufgerufene Seite existiert nicht."), 404

    @app.errorhandler(429)
    def _e429(err):
        return render_template("error.html",
                               status_code="429",
                               title="Zu viele Anfragen",
                               message="Bitte warte einen Moment."), 429

    @app.errorhandler(500)
    def _e500(err):
        return render_template("error.html",
                               status_code="500",
                               title="Interner Fehler",
                               message="Ein unerwarteter Fehler ist aufgetreten."), 500

    return app
