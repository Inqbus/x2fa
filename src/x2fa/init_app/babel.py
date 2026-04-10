from flask import Flask, request, session
from flask_babelplus import Babel, gettext, ngettext

from x2fa.config import cfg


def babel(app: Flask):
    """
    Initialize Flask-Babelplus with OIDC locale priority and template globals.
    Handles Error-404/500 cases gracefully (no RuntimeError).
    """
    # Configuration
    app.config['BABEL_DEFAULT_LOCALE'] = cfg.x2fa_babel.BABEL_DEFAULT_LOCALE
    app.config['BABEL_SUPPORTED_LOCALES'] = cfg.x2fa_babel.BABEL_SUPPORTED_LOCALES
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'

    # Initialize extension
    babel_ext = Babel(app)

    # 1. Locale Selector: OIDC session parameter > Browser preference
    @babel_ext.localeselector
    def _select_locale():
        # Priority 1: OIDC ui_locales from session
        oidc_req = session.get("oidc_request", {})
        ui_locales = oidc_req.get("ui_locales", "")
        for tag in ui_locales.split():
            lang = tag.split("-")[0].lower()
            if lang in cfg.x2fa_babel.BABEL_SUPPORTED_LOCALES:
                return lang

        # Priority 2: Browser Accept-Language header
        return request.accept_languages.best_match(
            cfg.x2fa_babel.BABEL_SUPPORTED_LOCALES,
            default=cfg.x2fa_babel.BABEL_DEFAULT_LOCALE
        )

    # 2. Template Globals (Error-Handler safe)
    @app.template_global()
    def _(text):
        """Gettext with fallback for outside-request-context (Error templates)"""
        try:
            return gettext(text)
        except RuntimeError:
            # Outside request context (e.g., CLI or 500-error before request)
            return text

    @app.template_global()
    def _n(singular, plural, n):
        """Ngettext with fallback"""
        try:
            return ngettext(singular, plural, n)
        except RuntimeError:
            return singular if n == 1 else plural

    @app.template_global()
    def get_locale():
        """Current locale or default (for <html lang="{{ get_locale() }}">)"""
        try:
            return _select_locale()
        except RuntimeError:
            # Outside request context
            return cfg.x2fa_babel.BABEL_DEFAULT_LOCALE
