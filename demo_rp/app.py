#!/usr/bin/env python3
"""
X2FA Demo RP — simulates an OIDC relying party for manual testing.

Prerequisites (run once after starting X2FA for the first time):
    flask add-client demo-rp https://x2fa-demo-rp.dev.inqbus.de/callback --secret testsecret

Usage:
    # Terminal 1 — X2FA
    X2FA_ENV=development FLASK_APP=wsgi:app uv run flask run --port 5000

    # Terminal 2 — this demo RP
    uv run python demo_rp.py

Then open http://localhost:5001

Updating translations:
    uv run pybabel extract -F demo_rp_babel.cfg -o demo_rp_translations/messages.pot demo_rp.py
    uv run pybabel update -i demo_rp_translations/messages.pot -d demo_rp_translations
    # edit .po files, then:
    uv run pybabel compile -d demo_rp_translations
"""

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

from dynaconf import Dynaconf
from pathlib import Path
from flask import Flask, redirect, render_template_string, request, session, url_for
from flask_babelplus import Babel, gettext as _

cfg = Dynaconf(
    root_path=Path(__file__).parent,
    settings_files=["demo_rp_settings.toml"],
    load_dotenv=True,
    envvar_prefix="DEMO_RP",
)

# ---------------------------------------------------------------------------
# Configuration — must match the registered OIDC client in X2FA
# ---------------------------------------------------------------------------

X2FA_URL      = cfg.X2FA_URL
DEMO_RP_URL   = cfg.DEMO_RP_URL
CLIENT_ID     = "demo-rp"
CLIENT_SECRET = cfg.CLIENT_SECRET
REDIRECT_URI  = DEMO_RP_URL + "/callback"
SECRET_KEY    = cfg.SECRET_KEY

SUPPORTED_UI  = {"de", "en"}
SUPPORTED_X2FA = {"de", "en", "fr", "es", "pt", "it", "nl", "pl",
                   "ru", "zh", "ja", "ko", "ar", "tr", "sv", "cs", "hu"}

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["BABEL_DEFAULT_LOCALE"]          = "en"
app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(
    os.path.dirname(__file__), "demo_rp_translations"
)

babel = Babel()


def _get_locale() -> str:
    return request.accept_languages.best_match(SUPPORTED_UI, default="en")


babel.init_app(app)

from flask_babelplus import get_locale
app.jinja_env.globals["get_locale"] = get_locale


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    """Returns a (code_verifier, code_challenge) PKCE S256 pair."""
    verifier  = secrets.token_urlsafe(43)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _decode_jwt_payload(token: str) -> dict:
    """Decodes the payload of a JWT without signature verification (display only)."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception as exc:
        return {"decode_error": str(exc)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(
        TEMPLATE,
        user=session.get("user"),
        claims=session.get("claims"),
        error=request.args.get("error", ""),
        x2fa_url=X2FA_URL,
        client_id=CLIENT_ID,
        redirect_uri=REDIRECT_URI,
    )


@app.route("/login")
def login():
    """Starts the OIDC flow: generates PKCE pair and redirects to X2FA /authorize."""
    mode       = request.args.get("mode", "verify")
    user_id    = request.args.get("user_id", "").strip() or "alice"
    ui_locales = request.args.get("ui_locales", "").strip()

    # If no explicit language was chosen, forward the browser's Accept-Language
    # so X2FA can honour it (best match against the supported set).
    if not ui_locales:
        best = request.accept_languages.best_match(SUPPORTED_X2FA)
        if best:
            ui_locales = best

    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    nonce = secrets.token_urlsafe(16)

    session["pkce_verifier"] = verifier
    session["state"]         = state
    session["nonce"]         = nonce

    scope  = "openid app:setup" if mode == "setup" else "openid"
    auth_params = {
        "client_id":             CLIENT_ID,
        "redirect_uri":          REDIRECT_URI,
        "response_type":         "code",
        "scope":                 scope,
        "state":                 state,
        "nonce":                 nonce,
        "login_hint":            user_id,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    }
    if ui_locales:
        auth_params["ui_locales"] = ui_locales
    params = urllib.parse.urlencode(auth_params)
    return redirect(f"{X2FA_URL}/authorize?{params}")


@app.route("/callback")
def callback():
    """Receives the authorization code, validates state, exchanges code for tokens."""
    error = request.args.get("error")
    if error:
        return redirect(url_for("index", error=error))

    code  = request.args.get("code", "")
    state = request.args.get("state", "")

    if not code:
        return redirect(url_for("index", error=_("No authorization code received.")))
    if state != session.get("state"):
        return redirect(url_for("index", error=_("State mismatch — possible CSRF attack.")))

    # Exchange authorization code for tokens
    body = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code_verifier": session.pop("pkce_verifier", ""),
    }).encode()

    req = urllib.request.Request(
        f"{X2FA_URL}/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            token_response = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        return redirect(url_for("index", error=_("Token exchange failed (%(code)s): %(detail)s", code=exc.code, detail=detail)))

    claims = _decode_jwt_payload(token_response.get("id_token", ""))

    session.pop("state", None)
    session.pop("nonce", None)
    session["user"]   = claims.get("sub", "unknown")
    session["claims"] = claims

    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

TEMPLATE = """\
<!DOCTYPE html>
<html lang="{{ get_locale() }}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>X2FA Test App</title>
<style>
  body  { font-family: system-ui, sans-serif; max-width: 620px; margin: 60px auto; padding: 0 1rem; color: #111; }
  h1    { font-size: 1.5rem; margin-bottom: 0.25rem; }
  .sub  { color: #666; margin-top: 0; font-size: 0.9rem; }
  .card { border: 1px solid #ddd; border-radius: 8px; padding: 1.2rem 1.5rem; margin: 1.2rem 0; background: #fafafa; }
  .ok   { color: #16a34a; font-weight: 600; font-size: 1.05rem; }
  .err  { color: #c00; font-weight: 600; }
  label { font-size: 0.9rem; font-weight: 600; display: block; margin-bottom: 0.3rem; }
  input[type=text] {
    padding: 0.5rem 0.7rem; border: 1px solid #ccc; border-radius: 5px;
    font-size: 1rem; width: 180px; margin-right: 0.5rem;
  }
  button {
    padding: 0.55rem 1.1rem; border: none; border-radius: 5px;
    cursor: pointer; font-size: 0.95rem; margin-right: 0.4rem; margin-top: 0.3rem;
  }
  .btn-blue { background: #1a56db; color: white; }
  .btn-gray { background: #6b7280; color: white; }
  .btn-red  { background: #dc2626; color: white; }
  pre  { background: #f4f4f4; padding: 0.8rem 1rem; border-radius: 6px; font-size: 0.82rem; overflow-x: auto; margin: 0.5rem 0 0; }
  .meta { font-size: 0.82rem; color: #555; }
  code { background: #eee; padding: 0.1rem 0.35rem; border-radius: 3px; font-size: 0.85rem; }
</style>
</head>
<body>

<h1>X2FA Test App</h1>
<p class="sub">{{ _("Simulates an OIDC relying party. X2FA must be running at") }} <code>{{ x2fa_url }}</code>.</p>

{% if error %}
<div class="card"><p class="err">&#x26A0; {{ error }}</p></div>
{% endif %}

{% if user %}
<div class="card">
  <p class="ok">&#10003; {{ _("Authenticated as") }} <strong>{{ user }}</strong></p>
  <p style="margin:0.8rem 0 0.3rem"><strong>{{ _("ID Token Claims") }}</strong></p>
  <pre>{{ claims | tojson(indent=2) }}</pre>
  <br>
  <a href="/logout"><button class="btn-red">{{ _("Log out") }}</button></a>
</div>
{% else %}
<div class="card">
  <p style="margin-top:0"><strong>{{ _("Not authenticated.") }}</strong> {{ _("Start a flow:") }}</p>
  <form action="/login" method="get">
    <label for="uid">{{ _("User ID") }} <span style="font-weight:400;color:#888">{{ _("(login_hint / sub in ID token)") }}</span></label>
    <input type="text" id="uid" name="user_id" value="alice" placeholder="alice">
    <br><br>
    <label for="loc">{{ _("Language") }} <span style="font-weight:400;color:#888">{{ _("(ui_locales — empty = server default)") }}</span></label>
    <select id="loc" name="ui_locales" style="padding:0.5rem 0.7rem;border:1px solid #ccc;border-radius:5px;font-size:1rem;margin-right:0.5rem;">
      <option value="">{{ _("— default —") }}</option>
      <option value="de">de — Deutsch</option>
      <option value="en">en — English</option>
      <option value="ar">ar — العربية</option>
      <option value="cs">cs — Čeština</option>
      <option value="es">es — Español</option>
      <option value="fr">fr — Français</option>
      <option value="hu">hu — Magyar</option>
      <option value="it">it — Italiano</option>
      <option value="ja">ja — 日本語</option>
      <option value="ko">ko — 한국어</option>
      <option value="nl">nl — Nederlands</option>
      <option value="pl">pl — Polski</option>
      <option value="pt">pt — Português</option>
      <option value="ru">ru — Русский</option>
      <option value="sv">sv — Svenska</option>
      <option value="tr">tr — Türkçe</option>
      <option value="zh">zh — 中文</option>
    </select>
    <br><br>
    <button type="submit" name="mode" value="verify" class="btn-blue">{{ _("Verify 2FA") }}</button>
    <button type="submit" name="mode" value="setup"  class="btn-gray">{{ _("Setup 2FA") }}</button>
  </form>
  <p class="meta" style="margin-top:1rem">
    <strong>{{ _("Verify") }}</strong> — {{ _("uses scope=openid, requires existing credentials.") }}<br>
    <strong>{{ _("Setup") }}</strong> &nbsp;— {{ _("uses scope=openid app:setup, registers new credentials.") }}
  </p>
</div>
{% endif %}

<div class="card meta">
  <strong>{{ _("Client config") }}</strong><br>
  {{ _("Client ID") }}: <code>{{ client_id }}</code> &nbsp;&bull;&nbsp;
  {{ _("Callback") }}: <code>{{ redirect_uri }}</code> &nbsp;&bull;&nbsp;
  X2FA: <code>{{ x2fa_url }}</code>
  <br><br>
  <strong>{{ _("First-time setup") }}</strong> ({{ _("run once in the X2FA directory") }}):<br>
  <code>flask add-client demo-rp http://localhost:5001/callback --secret testsecret</code>
</div>

</body>
</html>"""


if __name__ == "__main__":
    print("=" * 55)
    print(f"  X2FA Demo RP   →  {DEMO_RP_URL}")
    print(f"  X2FA expected  →  {X2FA_URL}")
    print("=" * 55)
    app.run(port=5001, debug=True)
