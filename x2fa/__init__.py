"""X2FA Flask App-Factory."""

import os
import secrets
from http import HTTPStatus

from flask import Flask, g, render_template

from x2fa.config import Config, E2ETestingConfig, ProductionConfig, TestingConfig
from x2fa.extensions import babel, db, limiter, migrate
from x2fa.oidc import oauth
from x2fa.oidc.grants import (
    S256OnlyCodeChallenge,
    X2FAAuthorizationCodeGrant,
    X2FAOpenIDCode,
    query_client,
    save_token,
)


def create_app(config_name: str = "production") -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "templates"
        ),
    )

    # Load configuration
    app.config.from_object(
        {
            "production": ProductionConfig,
            "testing": TestingConfig,
            "e2e": E2ETestingConfig,
            "development": Config,
        }.get(config_name, Config)
    )

    # Disable Authlib HTTPS requirement for development/testing
    if config_name in ("development", "testing", "e2e"):
        os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

    # Startup checks
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("FLASK_SECRET_KEY or X2FA_SECRET must be set!")
    if config_name == "production" and not app.config.get("RATELIMIT_STORAGE_URI"):
        raise RuntimeError(
            "REDIS_URL must be set in production (distributed rate-limiting)."
        )

    # Derive X2FA_ORIGIN if not explicitly set
    if not app.config.get("X2FA_ORIGIN"):
        domain = app.config["X2FA_DOMAIN"]
        app.config["X2FA_ORIGIN"] = f"https://{domain}"

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)

    # Internationalization: language preference comes from ui_locales in the
    # OIDC request (set by the RP), with Accept-Language as fallback.
    SUPPORTED = {
        "de",
        "en",
        "fr",
        "es",
        "pt",
        "it",
        "nl",
        "pl",
        "ru",
        "zh",
        "ja",
        "ko",
        "ar",
        "tr",
        "sv",
        "cs",
        "hu",
    }

    def _get_locale():
        from flask import request, session

        ui_locales = session.get("oidc_request", {}).get("ui_locales", "")
        for tag in ui_locales.split():
            lang = tag.split("-")[0].lower()
            if lang in SUPPORTED:
                return lang
        return request.accept_languages.best_match(SUPPORTED, default="de")

    babel.init_app(app, locale_selector=_get_locale)

    from flask_babel import get_locale

    app.jinja_env.globals["get_locale"] = get_locale

    # OIDC / Authlib setup
    oauth.init_app(app, query_client=query_client, save_token=save_token)
    oauth.register_grant(
        X2FAAuthorizationCodeGrant,
        [S256OnlyCodeChallenge(required=True), X2FAOpenIDCode(require_nonce=False)],
    )

    # Initialize WebAuthn
    from x2fa import webauthn_helpers

    webauthn_helpers.init_webauthn(app.config["X2FA_DOMAIN"])

    # Register blueprints
    from x2fa.routes.auth import auth_bp
    from x2fa.routes.setup import setup_bp
    from x2fa.routes.verify import verify_bp
    from x2fa.routes.totp import totp_bp
    from x2fa.routes.backup import backup_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(verify_bp)
    app.register_blueprint(totp_bp)
    app.register_blueprint(backup_bp)

    # Register CLI commands
    from x2fa.cli import register_commands

    register_commands(app)

    # Test-only blueprint for session injection (E2E Playwright tests)
    if config_name in ("testing", "e2e"):
        from x2fa.routes.test_helpers import test_bp

        app.register_blueprint(test_bp)

    # Create database tables (development/testing)
    if config_name in ("development", "testing", "e2e"):
        with app.app_context():
            db.create_all()

    # Security headers + CSP nonce
    @app.before_request
    def _set_nonce():
        g.nonce = secrets.token_urlsafe(16)

    # In test/e2e mode, allow localhost HTTP callbacks so Chromium follows OIDC
    # redirect chains through form submissions (Chrome enforces form-action on
    # the full redirect chain, blocking non-self http: targets otherwise).
    @app.after_request
    def _security_headers(response):
        nonce = getattr(g, "nonce", "")
        # Content-Security-Policy with per-request nonce
        csp_parts = [
            "default-src 'none'",
            f"script-src 'nonce-{nonce}'",
            "style-src 'unsafe-inline'",
            "img-src data:",  # for TOTP QR code
            "connect-src 'self'",
            f"form-action 'self' https:{'  http://127.0.0.1:*' if config_name in ('testing', 'e2e') else ''}",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Error pages
    @app.errorhandler(HTTPStatus.BAD_REQUEST)
    def _e400(err):
        from flask_babel import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.BAD_REQUEST.value),
            title=_("Invalid request"),
            message=str(err.description),
        ), HTTPStatus.BAD_REQUEST

    @app.errorhandler(HTTPStatus.UNAUTHORIZED)
    def _e401(err):
        from flask_babel import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.UNAUTHORIZED.value),
            title=_("Unauthorized"),
            message=_("Please sign in again."),
        ), HTTPStatus.UNAUTHORIZED

    @app.errorhandler(HTTPStatus.FORBIDDEN)
    def _e403(err):
        from flask_babel import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.FORBIDDEN.value),
            title=_("Access denied"),
            message=_("You do not have permission to access this page."),
        ), HTTPStatus.FORBIDDEN

    @app.errorhandler(HTTPStatus.NOT_FOUND)
    def _e404(err):
        from flask_babel import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.NOT_FOUND.value),
            title=_("Not found"),
            message=_("The requested page does not exist."),
        ), HTTPStatus.NOT_FOUND

    @app.errorhandler(HTTPStatus.TOO_MANY_REQUESTS)
    def _e429(err):
        from flask_babel import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.TOO_MANY_REQUESTS.value),
            title=_("Too many requests"),
            message=_("Please wait a moment."),
        ), HTTPStatus.TOO_MANY_REQUESTS

    @app.errorhandler(HTTPStatus.INTERNAL_SERVER_ERROR)
    def _e500(err):
        from flask_babel import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.INTERNAL_SERVER_ERROR.value),
            title=_("Internal error"),
            message=_("An unexpected error has occurred."),
        ), HTTPStatus.INTERNAL_SERVER_ERROR

    return app
