import secrets

from flask import Flask, g
from werkzeug.middleware.proxy_fix import ProxyFix

from x2fa.constants import AUTH_METHOD_TLS_CLIENT_AUTH, AUTH_METHOD_PRIVATE_KEY_JWT
from x2fa.helpers import webauthn_helpers
from x2fa.oidc import oauth
from x2fa.oidc.grants import (
    S256OnlyCodeChallenge,
    X2FAAuthorizationCodeGrant,
    X2FAOpenIDCode,
    X2FAPrivateKeyJwtAuth,
    authenticate_via_mtls,
    query_client,
    save_token,
)

def security(app: Flask):
    # Trust reverse proxy headers so Authlib sees https:// as the scheme
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # OIDC / Authlib setup
    oauth.init_app(app, query_client=query_client, save_token=save_token)
    oauth.register_grant(
        X2FAAuthorizationCodeGrant,
        [S256OnlyCodeChallenge(required=True), X2FAOpenIDCode(require_nonce=False)],
    )

    domain = app.config.x2fa.DOMAIN
    token_url = f"https://{domain}/token"
    oauth.register_client_auth_method(AUTH_METHOD_TLS_CLIENT_AUTH, authenticate_via_mtls)
    oauth.register_client_auth_method(AUTH_METHOD_PRIVATE_KEY_JWT, X2FAPrivateKeyJwtAuth(token_url))

    # # Test-only blueprint for session injection (E2E Playwright tests)
    # if app.config.x2fa.ENV_FOR_DYNACONF == 'testing':
    #     from x2fa.routes.test_helpers import test_bp
    #
    #     app.register_blueprint(test_bp)
    #

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
            "form-action 'self' https",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

