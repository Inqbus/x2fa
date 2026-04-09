import secrets

from flask import Flask, g

from x2fa import webauthn_helpers
from x2fa.oidc import oauth
from x2fa.oidc.grants import (
    S256OnlyCodeChallenge,
    X2FAAuthorizationCodeGrant,
    X2FAOpenIDCode,
    query_client,
    save_token,
)

def security(app: Flask):
    # OIDC / Authlib setup
    oauth.init_app(app, query_client=query_client, save_token=save_token)
    oauth.register_grant(
        X2FAAuthorizationCodeGrant,
        [S256OnlyCodeChallenge(required=True), X2FAOpenIDCode(require_nonce=False)],
    )

    webauthn_helpers.init_webauthn(app.config.x2fa.DOMAIN)

    # Test-only blueprint for session injection (E2E Playwright tests)
    if app.config.x2fa.TESTING:
        from x2fa.routes.test_helpers import test_bp

        app.register_blueprint(test_bp)


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
            f"form-action 'self' https:{'  http://127.0.0.1:*' if app.config.x2fa.TESTING else ''}",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ]
        response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

