from flask import Flask
from flask_babelplus import Babel

from x2fa.config import cfg

def babel(app: Flask):

    babel_extension = Babel(app)

    #
    # @app.before_request
    # def before_request():
    #     g.locale = get_locale()
    #     g.translations = support.Translations.load('translations', g.locale)
    #
    # # In Templates/Jinja:
    # @app.template_global()
    # def _(text):
    #     return g.translations.gettext(text)


# def _get_locale():
#     from flask import request, session
#
#     ui_locales = session.get("oidc_request", {}).get("ui_locales", "")
#     for tag in ui_locales.split():
#         lang = tag.split("-")[0].lower()
#         if lang in cfg.babel.BABEL_SUPPORTED_LOCALES:
#             return lang
#     return request.accept_languages.best_match(
#         cfg.babel.BABEL_SUPPORTED_LOCALES,
#         default=cfg.babel.BABEL_DEFAULT_LOCALE
#     )
#
#
#
# from flask_babel import get_locale
#
# app.jinja_env.globals["get_locale"] = get_locale
