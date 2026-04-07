"""OIDC endpoints: /authorize, /token, /.well-known/*, /jwks, /done demo callback."""

from http import HTTPStatus
from urllib.parse import urlencode

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _

from app.extensions import db, limiter
from app.models import AuthorizationCode, OIDCClient, SigningKey
from app.oidc import oauth

auth_bp = Blueprint("auth", __name__)


# ---------------------------------------------------------------------------
# OIDC Discovery
# ---------------------------------------------------------------------------


@auth_bp.route("/.well-known/openid-configuration")
def openid_configuration():
    """Standard OIDC discovery document (RFC 8414)."""
    domain = current_app.config["X2FA_DOMAIN"]
    base = f"https://{domain}"
    return jsonify(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "jwks_uri": f"{base}/.well-known/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["ES256"],
            "scopes_supported": ["openid", "x2fa:setup"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
            "code_challenge_methods_supported": ["S256"],
            "grant_types_supported": ["authorization_code"],
            "claims_supported": [
                "sub",
                "iss",
                "aud",
                "exp",
                "iat",
                "auth_time",
                "nonce",
            ],
        }
    )


@auth_bp.route("/.well-known/jwks.json")
def jwks():
    """JSON Web Key Set — public EC keys for ID token signature verification."""
    from authlib.jose import JsonWebKey
    from datetime import datetime, timezone

    keys = SigningKey.query.filter(
        SigningKey.active == True,
        SigningKey.expires_at > datetime.now(timezone.utc),
    ).all()
    jwk_list = []
    for sk in keys:
        # Pass PEM bytes directly to authlib (not a pre-loaded key object)
        jwk = JsonWebKey.import_key(
            sk.public_key_pem.encode(),
            {"kid": sk.kid, "use": "sig", "alg": sk.algorithm},
        )
        jwk_list.append(jwk.as_dict())

    return jsonify({"keys": jwk_list})


# ---------------------------------------------------------------------------
# Authorization Endpoint
# ---------------------------------------------------------------------------


@auth_bp.route("/authorize")
@limiter.limit(lambda: current_app.config["RATE_LIMIT_AUTHORIZE"])
def authorize():
    """
    OIDC Authorization Endpoint — two-phase flow:

    Phase 1 (first call): Validates OIDC parameters, stores them in the Flask
        session, then redirects the browser to the 2FA UI (/verify or /setup).

    Phase 2 (after 2FA): session['2fa_verified'] is True; Authlib issues the
        authorization code and redirects to the client's redirect_uri.
    """
    client_id = request.args.get("client_id", "")
    oidc_req = session.get("oidc_request", {})

    # Phase 2: 2FA complete — issue authorization code
    if (
        session.get("2fa_verified")
        and client_id
        and client_id == oidc_req.get("client_id")
    ):
        user_id = session["user_id"]
        response = oauth.create_authorization_response(grant_user=user_id)
        # Clean up OIDC state from session after code issuance
        session.pop("2fa_verified", None)
        session.pop("oidc_request", None)
        return response

    # Phase 1: validate parameters and start 2FA
    redirect_uri = request.args.get("redirect_uri", "")
    scope = request.args.get("scope", "")
    state = request.args.get("state")
    nonce = request.args.get("nonce")
    code_challenge = request.args.get("code_challenge", "")
    code_challenge_method = request.args.get("code_challenge_method", "")
    login_hint = request.args.get("login_hint", "").strip()

    if not all([client_id, redirect_uri, code_challenge, login_hint]):
        abort(
            HTTPStatus.BAD_REQUEST,
            _("client_id, redirect_uri, code_challenge, and login_hint are required."),
        )

    # Enforce PKCE S256 — plain is never accepted
    if code_challenge_method != "S256":
        abort(
            HTTPStatus.BAD_REQUEST, _("Only code_challenge_method=S256 is supported.")
        )

    client = OIDCClient.query.filter_by(client_id=client_id, active=True).first()
    if not client:
        abort(HTTPStatus.BAD_REQUEST, _("Unknown client_id."))
    if not client.check_redirect_uri(redirect_uri):
        abort(HTTPStatus.BAD_REQUEST, _("Invalid redirect_uri."))
    if "openid" not in scope:
        abort(HTTPStatus.BAD_REQUEST, _("scope must include 'openid'."))

    ui_locales = request.args.get("ui_locales", "").strip()

    # Store OIDC request parameters in the server-side session
    session["oidc_request"] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "response_type": "code",
        "login_hint": login_hint,
        "ui_locales": ui_locales,
    }
    session["user_id"] = login_hint
    session["2fa_verified"] = False
    session["setup_mode"] = "x2fa:setup" in scope

    if session["setup_mode"]:
        return redirect(url_for("setup.setup_choose"))
    return redirect(url_for("verify.verify_get"))


def _authorize_continue_url() -> str:
    """
    Reconstructs the /authorize URL from the stored OIDC session parameters.

    Called by 2FA routes after successful verification to redirect the browser
    back to the authorization endpoint (Phase 2).
    """
    oidc_req = session.get("oidc_request", {})
    return "/authorize?" + urlencode(
        {k: v for k, v in oidc_req.items() if v is not None}
    )


def _oidc_error_redirect(error: str, description: str = ""):
    """
    Redirects back to the RP's redirect_uri with an OIDC error response.

    Use this instead of abort() when the user cannot complete 2FA, so that
    the RP receives a proper error and no user-state details leak via the UI.
    """
    oidc_req = session.get("oidc_request", {})
    redirect_uri = oidc_req.get("redirect_uri", "")
    state = oidc_req.get("state")

    for key in ("oidc_request", "user_id", "2fa_verified", "setup_mode"):
        session.pop(key, None)

    if not redirect_uri:
        abort(HTTPStatus.BAD_REQUEST, _("Authentication not possible."))

    params = {"error": error}
    if description:
        params["error_description"] = description
    if state:
        params["state"] = state

    return redirect(f"{redirect_uri}?{urlencode(params)}")


# ---------------------------------------------------------------------------
# Token Endpoint
# ---------------------------------------------------------------------------


@auth_bp.route("/token", methods=["POST"])
@limiter.limit(lambda: current_app.config["RATE_LIMIT_TOKEN"])
def token():
    """OIDC Token Endpoint — exchanges an authorization code for tokens."""
    return oauth.create_token_response()


# ---------------------------------------------------------------------------
# Demo Callback (local testing only)
# ---------------------------------------------------------------------------


@auth_bp.route("/done")
def demo_done():
    """
    Demo callback that displays the received authorization code.
    Do NOT use in production — this endpoint accepts any redirect without
    authentication.
    """
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")

    if error:
        return render_template(
            "error.html",
            status_code=str(HTTPStatus.BAD_REQUEST.value),
            title="Error from OIDC server",
            message=error,
        ), HTTPStatus.BAD_REQUEST

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Demo Callback</title>
<style>
  body{{font-family:system-ui;max-width:500px;margin:60px auto;padding:0 1rem}}
  .ok{{color:#16a34a;font-size:1.3rem;font-weight:bold}}
  table{{border-collapse:collapse;width:100%}}
  td{{padding:.5rem;border-bottom:1px solid #eee}}
  code{{background:#f4f4f4;padding:.1rem .3rem;border-radius:3px;font-size:.9rem;word-break:break-all}}
</style></head>
<body>
<p class="ok">&#10003; Authorization code received</p>
<table>
  <tr><td><b>code</b></td><td><code>{code[:20]}&hellip;</code></td></tr>
  <tr><td><b>state</b></td><td><code>{state}</code></td></tr>
</table>
<p style="color:#888;font-size:.85rem;margin-top:2rem">
  This is a test endpoint. In a real application, the RP now exchanges the code
  at /token to obtain the ID token.
</p>
</body></html>"""
