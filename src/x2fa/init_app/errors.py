from http import HTTPStatus
from flask import Flask, render_template


def errors(app: Flask):
    # Error pages
    @app.errorhandler(HTTPStatus.BAD_REQUEST)
    def _e400(err):
        from flask_babelplus import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.BAD_REQUEST.value),
            title=_("Invalid request"),
            message=str(err.description),
        ), HTTPStatus.BAD_REQUEST


    @app.errorhandler(HTTPStatus.UNAUTHORIZED)
    def _e401(err):
        from flask_babelplus import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.UNAUTHORIZED.value),
            title=_("Unauthorized"),
            message=_("Please sign in again."),
        ), HTTPStatus.UNAUTHORIZED


    @app.errorhandler(HTTPStatus.FORBIDDEN)
    def _e403(err):
        from flask_babelplus import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.FORBIDDEN.value),
            title=_("Access denied"),
            message=_("You do not have permission to access this page."),
        ), HTTPStatus.FORBIDDEN


    @app.errorhandler(HTTPStatus.NOT_FOUND)
    def _e404(err):
        from flask_babelplus import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.NOT_FOUND.value),
            title=_("Not found"),
            message=_("The requested page does not exist."),
        ), HTTPStatus.NOT_FOUND


    @app.errorhandler(HTTPStatus.TOO_MANY_REQUESTS)
    def _e429(err):
        from flask_babelplus import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.TOO_MANY_REQUESTS.value),
            title=_("Too many requests"),
            message=_("Please wait a moment."),
        ), HTTPStatus.TOO_MANY_REQUESTS


    @app.errorhandler(HTTPStatus.INTERNAL_SERVER_ERROR)
    def _e500(err):
        from flask_babelplus import gettext as _

        return render_template(
            "error.html",
            status_code=str(HTTPStatus.INTERNAL_SERVER_ERROR.value),
            title=_("Internal error"),
            message=_("An unexpected error has occurred."),
        ), HTTPStatus.INTERNAL_SERVER_ERROR
