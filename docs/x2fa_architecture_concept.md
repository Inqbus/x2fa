# X2FA Projektskizze v5.8-final
**FIDO2 Microservice mit OIDC-Provider – Produktionsreife Authlib-Integration**
*Stand: 2026-03-31*

---

## 1. Konfiguration

### Config-Klasse mit explizitem DB-Mapping

```python
# app/config.py
import os
from datetime import timedelta

class Config:
    # Rückwärtskompatibel: FLASK_SECRET_KEY oder X2FA_SECRET
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or os.environ.get('X2FA_SECRET')
    X2FA_SECRET = os.environ.get('X2FA_SECRET') or os.environ.get('FLASK_SECRET_KEY')
    
    # NEU in v5.7: Explizites Mapping für SQLAlchemy (flask-sqlalchemy erwartet SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('DATABASE_URL') or           # Standard-Env-Var
        os.environ.get('X2FA_DATABASE_URL') or      # Legacy-Unterstützung
        'sqlite:///app.db'                          # Default
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}  # Verbindungs-Health-Check
    
    X2FA_DOMAIN = os.environ.get('X2FA_DOMAIN', 'localhost')
    
    SESSION_COOKIE_SECURE = True      # Nur HTTPS
    SESSION_COOKIE_HTTPONLY = True    # Kein JS-Zugriff
    SESSION_COOKIE_SAMESITE = 'Lax'   # CSRF-Schutz
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=5)
    
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL', 'memory://')
    # KORRIGIERT (v5.8): moving-window statt fixed-window (Burst-Angriff-Schutz)
    RATELIMIT_STRATEGY = "moving-window"

class TestingConfig(Config):
    """Konfiguration für Unit/Integration-Tests"""
    # KORRIGIERT (v5.8): Beide Secrets explizit setzen (nicht nur X2FA_SECRET)
    # Sonst reihenfolge-abhängig None wenn Env-Vars erst nach Import gesetzt
    SECRET_KEY = "test-secret-key-not-for-production"
    X2FA_SECRET = "test-secret-key-not-for-production"

    TESTING = True
    SESSION_COOKIE_SECURE = False     # HTTP im Testclient erlaubt
    SESSION_COOKIE_SAMESITE = None    # Kein SameSite für Test-Redirects
    RATELIMIT_STORAGE_URI = "memory://"  # Kein Redis in Tests
    RATELIMIT_STRATEGY = "moving-window"  # Konsistentes Verhalten in Tests
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

class ProductionConfig(Config):
    """Produktions-Konfiguration"""
    # Rate-Limiting für Production (Redis erforderlich bei Multi-Worker)
    # moving-window erfordert Redis (nicht memory://), aber ist sicherer
    RATELIMIT_STORAGE_URI = os.environ.get('REDIS_URL')  # Muss gesetzt sein!
```

### App-Factory mit Startup-Check

```python
# app/__init__.py (create_app)
def create_app(config_name='production'):
    app = Flask(__name__)
    
    # Konfiguration laden
    config_classes = {
        'production': ProductionConfig,
        'testing': TestingConfig,
        'development': Config
    }
    app.config.from_object(config_classes.get(config_name, Config))
    
    # NEU in v5.7: Startup-Check für SECRET_KEY
    if not app.config.get('SECRET_KEY'):
        raise RuntimeError(
            "FLASK_SECRET_KEY oder X2FA_SECRET muss gesetzt sein! "
            "Die App kann ohne Secret-Key nicht sicher betrieben werden."
        )
    
    # NEU in v5.7: Check für Production-Rate-Limiting
    if config_name == 'production' and not app.config.get('RATELIMIT_STORAGE_URI'):
        raise RuntimeError(
            "REDIS_URL muss in Production gesetzt sein für Distributed Rate-Limiting!"
        )
    
    # Extensions initialisieren
    db.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    secure_headers.init_app(app)
    
    # Routes registrieren...
    
    return app
```

---

## 2. Authlib-Integration (Korrigiert: PKCE S256-Enforcement)

### Grant-Klasse mit PKCE S256-Zwang

```python
from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core.grants import OpenIDCode
from authlib.oauth2 import OAuth2Error
from flask import session, current_app, redirect, request
from datetime import datetime, timezone, timedelta
import time

def save_token(token, request):
    """No-op für JWTs (stateless)"""
    pass

class X2FAAuthorizationCodeGrant(AuthorizationCodeGrant, OpenIDCode):
    """
    OpenIDCode Mixin für ID-Token Funktionalität.
    KORRIGIERT (v5.7): PKCE S256 erzwungen, plain explizit blockiert!
    """
    TOKEN_ENDPOINT_AUTH_METHODS = ['client_secret_post', 'client_secret_basic']
    
    def save_authorization_code(self, code, request):
        """
        KORRIGIERT (v5.7): Nur S256 erlaubt, plain wird abgelehnt!
        """
        # PKCE Method prüfen und erzwingen
        method = request.data.get('code_challenge_method', 'S256')
        if method != 'S256':
            raise OAuth2Error(
                'invalid_request', 
                'Only S256 code_challenge_method is supported. Plain is not allowed for security reasons.'
            )
        
        # User-ID aus Flask-Session (nach 2FA-Verification)
        user_id = session.get('user_id')
        if not user_id:
            raise OAuth2Error('login_required', '2FA not completed')
        
        # AuthorizationCode-Objekt erstellen
        auth_code = AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            user_id=user_id,
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            nonce=request.data.get('nonce'),
            code_challenge=request.data.get('code_challenge'),
            code_challenge_method='S256',  # Hardcoded S256
            auth_time=int(time.time()),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60)
        )
        db.session.add(auth_code)
        db.session.commit()
        return auth_code
    
    def query_authorization_code(self, code, client):
        """Code laden und Validität prüfen"""
        auth_code = AuthorizationCode.query.filter_by(
            code=code,
            client_id=client.client_id
        ).first()
        
        if not auth_code:
            return None
        if auth_code.is_expired():
            return None
        if auth_code.used:
            return None
        return auth_code
    
    def delete_authorization_code(self, authorization_code):
        """Als verbraucht markieren (Authlib löscht nicht physisch)"""
        authorization_code.used = True
        db.session.commit()
    
    def authenticate_user(self, authorization_code):
        """Gibt User-ID zurück für ID-Token 'sub' Claim"""
        return authorization_code.user_id
    
    def get_jwt_config(self, grant):
        """ID-Token Signierung Konfiguration"""
        from app.services.crypto import CryptoService
        crypto = CryptoService(current_app.config['X2FA_SECRET'])
        
        signing_key = SigningKey.query.filter(
            SigningKey.active == True,
            (SigningKey.expires_at == None) | (SigningKey.expires_at > datetime.now(timezone.utc))
        ).order_by(SigningKey.created_at.desc()).first()
        
        if not signing_key:
            raise RuntimeError("No active signing key! Run 'flask init-keys' first")
        
        private_key = signing_key.get_private_key(crypto.get_fernet())
        
        return {
            'key': private_key,
            'alg': 'ES256',
            'iss': f"https://{current_app.config['X2FA_DOMAIN']}",
            'exp': 60,
            'kid': signing_key.kid
        }
    
    def generate_user_info(self, user_id, scope):
        """Minimal user info für ID-Token"""
        return {'sub': user_id}
    
    def exists_nonce(self, nonce, request):
        """
        Replay-Schutz: Prüfen ob nonce bereits verwendet.
        KORRIGIERT (v5.7): Cleanup darf Codes NICHT vor 1h löschen (siehe unten)!
        """
        if not nonce:
            return False
        return AuthorizationCode.query.filter_by(nonce=nonce).first() is not None

# Initialisierung
def query_client(client_id):
    return OIDCClient.query.filter_by(client_id=client_id, active=True).first()

oauth = AuthorizationServer(
    app, 
    query_client=query_client, 
    save_token=save_token
)

# CodeChallenge bleibt required, aber plain wird in save_authorization_code blockiert
oauth.register_grant(X2FAAuthorizationCodeGrant, [CodeChallenge(required=True)])
```

---

## 3. Rate-Limiting (Korrigiert: Spezifische Auth-Limits)

### Dedizierte Limits für sensible Endpunkte

```python
# app/extensions.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",  # Wird in create_app überschrieben
    default_limits=["200 per day", "50 per hour"],  # Für statische Seiten
    headers_enabled=True
)

# app/routes/totp.py
from app.extensions import limiter
from flask import Blueprint, request, jsonify

totp_bp = Blueprint('totp', __name__)

@totp_bp.route("/setup", methods=["GET"])
@login_required
def totp_setup():
    """TOTP Setup QR-Code anzeigen"""
    # ... Implementation ...

@totp_bp.route("/verify", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")  # KORRIGIERT (v5.7): Strikt für TOTP!
def totp_verify_post():
    """
    TOTP-Verifikation mit striktem Rate-Limit.
    10^6 mögliche Codes → Brute Force bei 50/h über IPs möglich, daher 5/min.
    """
    user_id = session.get('user_id')
    code = request.json.get('code')
    
    if verify_totp(user_id, code):
        session['2fa_verified'] = True
        session.permanent = True
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

# app/routes/backup.py
from app.extensions import limiter

backup_bp = Blueprint('backup', __name__)

@backup_bp.route("/verify", methods=["POST"])
@limiter.limit("3 per minute; 10 per hour")  # KORRIGIERT (v5.7): Noch strikter für Backup-Codes!
def backup_verify_post():
    """
    Backup-Code Verifikation.
    8 Hex-Zeichen = 4 Mrd. Kombinationen → sehr striktes Limit nötig!
    """
    user_id = session.get('user_id')
    code = request.json.get('code')
    
    if verify_backup_code(user_id, code):
        session['2fa_verified'] = True
        session.permanent = True
        return jsonify({"success": True})
    return jsonify({"success": False}), 401

# app/routes/webauthn.py
from app.extensions import limiter

webauthn_bp = Blueprint('webauthn', __name__)

@webauthn_bp.route("/verify/complete", methods=["POST"])
@limiter.limit("10 per minute; 30 per hour")  # KORRIGIERT (v5.7): Moderat für WebAuthn
def verify_complete():
    """
    WebAuthn Assertion verifizieren.
    WebAuthn ist replay-resistent durch Challenge-Signaturen, 
    aber Rate-Limiting schützt vor DoS auf der DB.
    """
    # ... Implementation ...

# OIDC-Endpunkte (in routes/auth.py)
@limiter.limit("10 per minute; 100 per hour")  # KORRIGIERT (v5.7): Separates Limit für /authorize
@app.route("/authorize")
def authorize():
    # ... Implementation ...

@limiter.limit("20 per minute")  # KORRIGIERT (v5.7): Separates Limit für /token
@app.route("/token", methods=["POST"])
def issue_token():
    # ... Implementation ...
```

---

## 4. Cleanup-Policy (Korrigiert: Nonce-Schutz erhalten)

### Sicherer Cleanup-Job

```python
# app/services/cleanup.py oder in cli.py
from datetime import datetime, timezone, timedelta
from app.models import AuthorizationCode
from app.extensions import db

def cleanup_authorization_codes():
    """
    KORRIGIERT (v5.7): Cleanup darf Codes NICHT vor 1h löschen!
    Nonces müssen länger gültig bleiben als ID-Token-Lebensdauer (60s),
    aber wir behalten 1h als Sicherheitspuffer für Replay-Schutz.
    """
    # NUR Codes löschen, die älter als 1 Stunde sind
    # → Nonce-Replay-Schutz bleibt erhalten
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
    
    old_codes = AuthorizationCode.query.filter(
        AuthorizationCode.expires_at < cutoff_time
    ).all()
    
    count = len(old_codes)
    for code in old_codes:
        db.session.delete(code)
    
    db.session.commit()
    return count

# Flask CLI Command
@app.cli.command('cleanup-codes')
@with_appcontext
def cleanup_codes():
    """Bereinigt alte Authorization Codes (sicher für Nonce-Schutz)"""
    count = cleanup_authorization_codes()
    click.echo(f"Deleted {count} authorization codes older than 1 hour")

# NICHT erlaubt (würde Nonce-Schutz brechen):
# AuthorizationCode.query.filter(AuthorizationCode.used == True).delete()
# AuthorizationCode.query.filter(AuthorizationCode.expires_at < datetime.now(timezone.utc)).delete()
```

---

## 5. Zusammenfassung aller Fixes (v5.6 → v5.8-final)

| # | Problem | Schwere | Fix |
|---|---------|---------|-----|
| 1 | **PKCE plain nicht blockiert** | Hoch | `method != 'S256'` check in `save_authorization_code()` (v5.7) |
| 2 | **Rate-Limits zu locker** | Hoch | Dedizierte Limits: TOTP 5/min, Backup 3/min, WebAuthn 10/min (v5.7) |
| 3 | **Nonce-Schutz bricht bei Cleanup** | Mittel | Cleanup nur für Codes >1h alt (v5.7) |
| 4 | **DATABASE_URL Mapping fehlt** | Funktional | `SQLALCHEMY_DATABASE_URI` explizit gemappt, `pool_pre_ping` (v5.7) |
| 5 | **SECRET_KEY = None möglich** | Funktional | Startup-Check in `create_app()` mit `RuntimeError` (v5.7) |
| 6 | **fixed-window Burst-Angriffe** | Mittel | `RATELIMIT_STRATEGY = "moving-window"` (v5.8) |
| 7 | **TestingConfig SECRET_KEY reihenfolge-abhängig** | Funktional | `SECRET_KEY` explizit in `TestingConfig` gesetzt (v5.8) |

---

*Die v5.8-final ist production-ready, testbar, gegen Burst- und Brute-Force-Angriffe geschützt, mit korrektem PKCE/Nonce-Handling.*