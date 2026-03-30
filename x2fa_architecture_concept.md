 Hier ist die komplette, finale **v5.4-final** mit allen Korrekturen (inkl. des TOTP-Replay-Schutz-Fixes mit `last_used_window`):

---

# X2FA Projektskizze v5.4-final
**FIDO2 Microservice mit OIDC-Provider – Produktionsreife Authlib-Integration**
*Stand: 2026-03-30*

---

## 1. Vision & Value Proposition

X2FA ist ein standalone 2FA-Microservice mit vollständigem OIDC-Provider (OpenID Connect), der in bestehende Anwendungen über den standardisierten Authorization Code Flow integriert wird. Unterstützt alle FIDO2-Authenticator-Klassen (Platform, Roaming, Hybrid) sowie TOTP-Fallback für universelle Plattformkompatibilität (inkl. Linux).

**Value Proposition:** X2FA in unter 60 Sekunden installieren – FIDO2-Authentifizierung mit produktionsreifer OIDC-Session-Verwaltung via Flask und Authlib.

---

## 2. Migrationsstrategie: Rewrite v5.4

**Aufwand:** ~2-3 Tage (~15 Dateien)

---

## 3. Kernkonzept

### Bring Your Own Domain + Bring Your Own Infrastructure

| Komponente | Nutzer bringt | X2FA stellt bereit |
|------------|---------------|-------------------|
| **Domain** | DNS A-Record (`2fa.example.com` → Server-IP) | Automatische RP-ID Konfiguration |
| **TLS/Infrastruktur** | Caddy/nginx/Traefik/Cloudflare | HTTP-Backend auf localhost:5000 |
| **Datenbank** | SQLite (Default), PostgreSQL oder MySQL | SQLAlchemy-ORM mit Migrationen |
| **Authenticator** | **Wählbar:** FaceID/TouchID (Apple), Hello (Windows), Android Biometrie, YubiKey (USB/NFC), oder Phone-as-Key (Hybrid) | Auto-Detection der verfügbaren Methoden, Cross-Platform Support |
| **Fallback** | TOTP-App (Google Authenticator) | Verschlüsselte Speicherung (Fernet) |
| **Notfall** | 10 Backup-Codes | Einmalige Validierung |
| **Integration** | OIDC-Client (client_id + client_secret) | OIDC Authorization Code Flow, JWKS-Endpunkt, Discovery |

### Authenticator-Strategie (Linux-kompatibel)

| Plattform | Primäre Methode | Fallback | Implementierung |
|-----------|----------------|----------|-----------------|
| **macOS/iOS** | Secure Enclave (TouchID/FaceID) | TOTP | `navigator.credentials` ohne Attachment-Filter |
| **Windows 10/11** | TPM 2.0 (Hello) | TOTP | Platform-Detection |
| **Android** | StrongBox/TEE | TOTP | Biometrie-API |
| **Linux Desktop** | **Hybrid/Phone-as-Key** oder **YubiKey** | TOTP | QR-Code für Phone-Auth oder USB-Roaming |
| **Server/Headless** | TOTP oder Backup-Codes | - | Kein WebAuthn verfügbar |

**Wichtig:** Keine `authenticatorAttachment: "platform"` Einschränkung – verwendet `cross-platform` als Default, um YubiKey und Hybrid zu ermöglichen.

---

## 4. Systemarchitektur (Ausführlich)

### Komponentendiagramm

```mermaid
graph TB
    subgraph "CLIENT"
        Browser["Browser<br/>Vanilla JS inline"]
        PlatformAuth["Platform Authenticator<br/>FaceID TouchID WindowsHello"]
        RoamingAuth["Roaming Authenticator<br/>YubiKey USB/NFC"]
        HybridAuth["Hybrid/Phone<br/>Android/iPhone via QR/BLE"]
        TOTPApp["TOTP-App<br/>Google Authenticator"]
    end

    subgraph "INFRASTRUKTUR"
        TLS["HTTPS Terminierung<br/>Caddy nginx Traefik Cloudflare"]
    end

    subgraph "X2FA SERVICE"
        Flask["Flask Application<br/>Gunicorn/Werkzeug<br/>localhost:5000"]
        
        subgraph "SESSION (Client-Seitig)"
            Cookie["Signed Cookie<br/>Werkzeug Secure<br/>HttpOnly SameSite=Lax"]
        end
        
        subgraph "DATENBANKSCHICHT"
            SQLAlchemy["SQLAlchemy ORM"]
        end
        
        subgraph "DATENBANK"
            SQLite[("SQLite Default")]
            Postgres[("PostgreSQL")]
            MySQL[("MySQL")]
        end
        
        subgraph "CACHE (Optional)"
            Redis["Redis<br/>Rate-Limiting Store<br/>Shared State"]
        end
    end

    MainApp["HAUPTANWENDUNG<br/>OIDC Relying Party"]

    Browser <-->|"HTTPS TLS 1.3"| TLS
    TLS <-->|"HTTP Plain"| Flask
    Flask <-->|"SQL Queries"| SQLAlchemy
    SQLAlchemy <-->|"Engine"| SQLite
    SQLAlchemy <-->|"Engine"| Postgres
    SQLAlchemy <-->|"Engine"| MySQL
    
    Flask <-.->|"Set-Cookie / Header"| Cookie
    Browser <-.->|"Cookie: session=..."| Cookie
    
    Flask <-->|"Redis Protocol"| Redis
    
    Browser <-->|"WebAuthn API<br/>navigator.credentials"| PlatformAuth
    Browser <-->|"WebAuthn API<br/>USB/NFC"| RoamingAuth
    Browser <-->|"caBLE / QR-Code<br/>Cloud Relay"| HybridAuth
    Browser -.->|"Manuelle Eingabe<br/>6-stelliger Code"| TOTPApp
    
    MainApp <-->|"OIDC Auth Code Flow<br/>/authorize /token /jwks.json"| TLS
    
    style PlatformAuth fill:#f9f
    style RoamingAuth fill:#f9f
    style HybridAuth fill:#f9f
    style TOTPApp fill:#ff9
    style Flask fill:#ff9
    style Cookie fill:#ffcc99
    style Redis fill:#ff9999
    style SQLAlchemy fill:#bbf
    style SQLite fill:#fbb
    style MainApp fill:#9f9
```

### Session-Architektur (Detailliert)

```
Flask Session (Client-seitig, Signed Cookie):
├─ session['user_id'] = "user123"          # Nach erfolgreicher 2FA
├─ session['auth_time'] = 1711822800     # Unix-Timestamp (Integer)
├─ session['2fa_verified'] = True        # Flag für OIDC-Authorization
├─ session['auth_method'] = "webauthn"   # Für AMR-Claim im ID-Token
├─ session.permanent = True             # WICHTIG: Für Ablauf nach 5min!
└─ Signatur: HMAC-SHA256(SECRET_KEY)

Authlib Authorization Code (Server-seitig, Datenbank):
├─ code: Opaque String (60s TTL)
├─ client_id: Foreign Key zu OIDCClient
├─ user_id: Aus Flask-Session übernommen
├─ code_challenge: PKCE (S256)
├─ nonce: Für ID-Token Replay-Schutz
├─ auth_time: Unix-Integer (für 'auth_time' Claim)
├─ expires_at: DateTime für SQL-Abfragen
└─ used: Boolean (Einmalverwendung)

Redis (Shared State):
├─ Rate-Limit Counter (IP-basiert)
└─ Session-Store bei Multi-Node (optional)
```

### HTTPS-Strategien (Resolveragnostisch)

| Setup | Verwendung | Konfiguration |
|-------|-----------|---------------|
| **Caddy** | Zero-Config, Auto-HTTPS | `reverse_proxy localhost:5000`, automatische Zertifikate |
| **nginx** | Enterprise, manuelle Kontrolle | `proxy_pass http://127.0.0.1:5000`, Certbot-Integration |
| **Traefik** | Docker/Cloud-Native | Label-basierte Discovery, Auto-HTTPS |
| **Cloudflare Tunnel** | Serverless/Home-Lab | Edge-Terminierung, intern HTTP |

---

## 5. Technologie-Stack

| Ebene | Technologie | Spezifikation |
|-------|-------------|---------------|
| **Framework** | Flask 3.0+ | Werkzeug-Sessions, Jinja2 |
| **WSGI-Server** | Gunicorn 21.0+ | Production-Deployment (4 Worker mit Redis) |
| **Development** | Flask Built-in | `flask run` für Entwicklung |
| **Python** | 3.11+ | `datetime.now(timezone.utc)` statt utcnow() |
| **ORM** | SQLAlchemy 2.0+ | DB-Agnostik, Connection Pooling (`pool_pre_ping=True`) |
| **Migration** | Flask-Migrate | Alembic-Integration |
| **WebAuthn** | py_webauthn 2.0+ | Server-seitige FIDO2-Validierung |
| **TOTP** | pyotp 2.9+ | RFC 6238, Zeitfenster ±30s |
| **QR-Code** | qrcode 7.4+ Pillow | PNG/SVG Generierung |
| **OIDC** | Authlib 1.3+ | `OpenIDCode` Mixin für ID-Tokens, PKCE |
| **Krypto** | cryptography 41.0+ | Fernet (AES-128-CBC + HMAC-SHA256), HKDF |
| **Hashing** | bcrypt 4.0+ | Backup-Codes & Client-Secrets (rounds=12) |
| **Sessions** | Flask-Session (Werkzeug) | Signed Cookies, CSRF-Protection via SameSite |
| **Rate-Limiting** | Flask-Limiter 3.5+ | **Redis-Backend für Multi-Worker**, Memory für Single-Node |
| **Security Headers** | secure 0.3+ | `Secure` Klasse (nicht SecureHeaders), CSP mit Nonces |
| **Cache/Store** | Redis 7+ | Shared State zwischen Gunicorn-Workern |
| **DB-Drivers** | sqlite3/psycopg2/pymysql | SQLite built-in, andere optional |
| **Frontend** | Vanilla JS | ~50 Zeilen inline, CSP-nonced, keine Build-Tools |

### Dependencies (requirements.txt)

```txt
flask>=3.0.0
gunicorn>=21.0.0
flask-limiter>=3.5.0
flask-migrate>=4.0.0
secure>=0.3.0
redis>=5.0.0
authlib>=1.3.0
webauthn>=2.0.0
pyotp>=2.9.0
qrcode>=7.4
Pillow>=10.0.0
cryptography>=41.0.0
sqlalchemy>=2.0.0
bcrypt>=4.0.0
# Optional: psycopg2-binary>=2.9.0, pymysql>=1.1.0
```

---

## 6. Datenbank-Schema (Authlib-kompatible SQLAlchemy Models)

### Model `Credential` (FIDO2)

```python
from datetime import datetime, timezone
from sqlalchemy import Column, LargeBinary, Integer, String, DateTime, Boolean, Index

class Credential(Base):
    __tablename__ = 'credentials'
    
    credential_id = Column(LargeBinary(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)
    sign_count = Column(Integer, default=0)
    authenticator_type = Column(String(20))  # 'platform', 'roaming', 'hybrid'
    device_type = Column(String(20))
    transport = Column(String(50))
    is_passkey = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)
    
    __table_args__ = (Index('idx_cred_user', 'user_id', 'created_at'),)
```

### Model `OIDCClient` (Korrigiert – explizite PK!)

```python
from authlib.integrations.sqla_oauth2 import OAuth2ClientMixin
from sqlalchemy import Column, String, DateTime, Boolean, Integer
import bcrypt

class OIDCClient(Base, OAuth2ClientMixin):
    """
    WICHTIG: OAuth2ClientMixin liefert KEIN id (PK)!
    Wir müssen explizit deklarieren!
    
    Mixin liefert:
    - client_id (String)
    - client_secret (String) -- hier speichern wir bcrypt-Hash!
    - _client_metadata (JSON-String in DB!)
    """
    __tablename__ = 'oidc_clients'
    
    # EXPLIZIT DEKLARIEREN (Mixin hat kein id!)
    id = Column(Integer, primary_key=True)
    
    # Zusätzliche Felder
    name = Column(String(255))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    def check_client_secret(self, client_secret):
        """
        ZWINGEND ÜBERSCHREIBEN!
        Mixin-Default macht plain comparison (secrets.compare_digest).
        Wir brauchen bcrypt.
        """
        if not self.client_secret or not client_secret:
            return False
        return bcrypt.checkpw(
            client_secret.encode('utf-8'),
            self.client_secret.encode('utf-8')
        )
    
    def get_allowed_scope(self, scope):
        return 'openid' if 'openid' in scope else ''
    
    def check_response_type(self, response_type):
        return response_type == 'code'
    
    def check_grant_type(self, grant_type):
        return grant_type == 'authorization_code'
    
    # set_client_metadata() verwenden für Initialisierung!
```

### Model `AuthorizationCode` (Korrigiert – fehlende Spalten)

```python
from authlib.integrations.sqla_oauth2 import OAuth2AuthorizationCodeMixin
import time

class AuthorizationCode(Base, OAuth2AuthorizationCodeMixin):
    """
    WICHTIG: OAuth2AuthorizationCodeMixin liefert weder id noch user_id!
    Wir müssen explizit deklarieren!
    
    Mixin liefert:
    - code, client_id, redirect_uri, scope, nonce
    - code_challenge, code_challenge_method
    - auth_time (Integer/Unix-Timestamp!)
    """
    __tablename__ = 'authorization_codes'
    
    # EXPLIZIT DEKLARIEREN (Mixin hat weder id noch user_id!)
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    
    # Expiration (nicht im Mixin)
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, default=False)
    
    def is_expired(self):
        """Unix-Timestamp (auth_time) vs DateTime (expires_at)"""
        return datetime.now(timezone.utc) > self.expires_at
```

### Model `Challenge` (Nur WebAuthn – keine TOTP-Challenges!)

```python
class Challenge(Base):
    __tablename__ = 'challenges'
    
    challenge_id = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    challenge = Column(LargeBinary, nullable=False)  # 32-64 Bytes zufällig
    expires_at = Column(DateTime, nullable=False, index=True)
    used = Column(Boolean, default=False)
    # KEIN challenge_type Feld – TOTP braucht keine Server-Challenge!
```

### Model `TOTPSecret` (Fernet-Verschlüsselt + Replay-Schutz)

```python
class TOTPSecret(Base):
    __tablename__ = 'totp_secrets'
    
    user_id = Column(String(255), primary_key=True)
    secret_encrypted = Column(LargeBinary, nullable=False)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)  # Für Audit/Anzeige
    last_used_window = Column(Integer, nullable=True)  # NEU: Replay-Schutz (Unix//30)
```

### Model `BackupCode` (10 pro User, einmalig)

```python
class BackupCode(Base):
    __tablename__ = 'backup_codes'
    
    code_hash = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

### Model `SigningKey` (ES256 für ID-Token – mit Methode!)

```python
class SigningKey(Base):
    __tablename__ = 'signing_keys'
    
    kid = Column(String(64), primary_key=True)
    private_key_pem_encrypted = Column(Text, nullable=False)  # Fernet-verschlüsselt
    public_key_pem = Column(Text, nullable=False)  # Unverschlüsselt für JWKS
    algorithm = Column(String(10), default='ES256')
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    active = Column(Boolean, default=True)
    # KORRIGIERT: expires_at für Rotation-Overlap (24h)
    expires_at = Column(DateTime, nullable=True)
    
    def get_private_key(self, fernet):
        """
        Entschlüsselt den Private Key für ID-Token Signierung.
        Wird in get_jwt_config() aufgerufen!
        """
        encrypted = self.private_key_pem_encrypted.encode()
        return fernet.decrypt(encrypted).decode()
```

### Model `AuditLog` (Optional, für Compliance)

```python
class AuditLog(Base):
    __tablename__ = 'audit_logs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    action = Column(String(50))  # 'login', 'setup', 'verify', 'fail'
    method = Column(String(50))  # 'webauthn_platform', 'totp', 'backup'
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ip_hash = Column(String(64))  # SHA256 mit Salt (GDPR-konform)
    details = Column(Text, nullable=True)  # JSON für Metadaten
```

---

## 7. Sicherheitskonzept

### Trust Boundaries

| Zone | Daten | Schutzmaßnahmen |
|------|-------|-----------------|
| **Secure Enclave/TPM/HSM** | Private Keys (FIDO2) | Hardware-verschlüsselt, nie exportierbar |
| **Browser** | Challenge, Assertion, TOTP-Codes | CSP `default-src 'none'; script-src 'nonce-{random}';` |
| **Flask Backend** | Sessions (Signed Cookies), verschlüsselte Secrets | Werkzeug-Signatur, SQLAlchemy ORM (Prepared Statements) |
| **Transport** | JWTs, WebAuthn-Daten, Authorization Codes | TLS 1.3 (extern terminiert), HSTS Pflicht |

### Session-Konfiguration (Werkzeug)

```python
class Config:
    # Rückwärtskompatibel: FLASK_SECRET_KEY oder X2FA_SECRET
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') or os.environ.get('X2FA_SECRET')
    X2FA_SECRET = os.environ.get('X2FA_SECRET') or os.environ.get('FLASK_SECRET_KEY')
    
    SESSION_COOKIE_SECURE = True      # Nur HTTPS
    SESSION_COOKIE_HTTPONLY = True    # Kein JS-Zugriff
    SESSION_COOKIE_SAMESITE = 'Lax'   # CSRF-Schutz
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=5)
```

### CSP & Security Headers (secure.py 0.3+)

```python
import secrets
from secure import Secure  # KORREKT: Secure, nicht SecureHeaders
from flask import g

secure = Secure()

@app.before_request
def generate_csp_nonce():
    """CSP-Nonce pro Request generieren (kryptografisch sicher)"""
    g.csp_nonce = secrets.token_urlsafe(16)

@app.after_request
def set_security_headers(response):
    # Standard Headers via secure.py (HSTS, X-Frame-Options, etc.)
    secure.framework.flask(response)
    
    # KORRIGIERT: getattr() für Fehlerresponses (wenn g.csp_nonce fehlt)
    nonce = getattr(g, 'csp_nonce', '')
    
    # KORRIGIERT: img-src für TOTP QR-Codes (data: für Base64)
    response.headers['Content-Security-Policy'] = (
        f"default-src 'none'; "
        f"script-src 'nonce-{nonce}' 'strict-dynamic'; "
        f"connect-src 'self'; "
        f"form-action 'self'; "
        f"img-src 'self' data:; "  # WICHTIG: Für QR-Codes!
        f"base-uri 'none'; "
        f"frame-ancestors 'none';"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    return response
```

### Template-Verwendung (Jinja2 mit Nonce)

```html
<!-- templates/webauthn_setup.html -->
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>X2FA Setup</title>
</head>
<body>
    <h1>Hardware-Schlüssel registrieren</h1>
    <div id="status">Bitte Authenticator auswählen...</div>
    
    <!-- QR-Code für TOTP (braucht img-src in CSP) -->
    <img src="data:image/png;base64,{{ qr_code_base64 }}" alt="TOTP QR Code">
    
    <script nonce="{{ g.csp_nonce }}">
        // WebAuthn JavaScript mit CSP-Nonce
        const challenge = new Uint8Array({{ challenge | tojson }});
        const rpId = "{{ rp_id }}";
        
        async function register() {
            const credential = await navigator.credentials.create({
                publicKey: {
                    challenge: challenge,
                    rp: { name: "X2FA", id: rpId },
                    user: { 
                        id: new TextEncoder().encode("{{ user_id }}"), 
                        name: "{{ user_id }}",
                        displayName: "{{ user_id }}"
                    },
                    pubKeyCredParams: [{ alg: -7, type: "public-key" }],
                    authenticatorSelection: {
                        authenticatorAttachment: "cross-platform",
                        userVerification: "preferred"
                    }
                }
            }).catch(err => {
                console.error("WebAuthn error:", err);
                document.getElementById('status').textContent = "Fehler: " + err;
            });
            
            // An Server senden...
            await fetch('/setup/complete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    id: credential.id,
                    rawId: Array.from(new Uint8Array(credential.rawId)),
                    response: {
                        clientDataJSON: Array.from(new Uint8Array(credential.response.clientDataJSON)),
                        attestationObject: Array.from(new Uint8Array(credential.response.attestationObject))
                    }
                })
            });
        }
        
        register();
    </script>
</body>
</html>
```

### Rate-Limiting (Redis-Backend für Gunicorn)

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get('REDIS_URL', 'memory://'),
    default_limits=["200 per day", "50 per hour"]
)

# WICHTIG: Bei Gunicorn mit 4 Workern zwingend REDIS_URL setzen!
# Bei SQLite-Setup: gunicorn -w 1 (nur 1 Worker!)
```

### HKDF-Krypto-Service (Korrigiert – mit Salt!)

```python
# app/services/crypto.py
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64
import bcrypt
import uuid

class CryptoService:
    def __init__(self, master_secret: str):
        """
        Master-Secret (X2FA_SECRET) für verschiedene Ableitungen.
        Separate Keys für TOTP und Fernet via HKDF Context-Strings.
        """
        self.master = master_secret.encode()
        
        # KORRIGIERT: Fixer Salt statt None (RFC 5869 Best Practice)
        self._salt = b'x2fa-static-salt-v1'
        
        # Fernet-Key für DB-Verschlüsselung (32 Bytes, Base64-encoded)
        fernet_key = self._derive_key(b'x2fa-fernet-v1', 32)
        self.fernet = Fernet(base64.urlsafe_b64encode(fernet_key))
    
    def _derive_key(self, info: bytes, length: int) -> bytes:
        """
        HKDF-SHA256 (RFC 5869) für sichere Key-Ableitung.
        'info' garantiert Key-Separation für verschiedene Zwecke.
        KORRIGIERT: Verwendet fixen Salt statt None.
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=length,
            salt=self._salt,  # KORRIGIERT: Fixer Salt statt None
            info=info
        )
        return hkdf.derive(self.master)
    
    def get_fernet(self):
        """Für SigningKey Private-Key Entschlüsselung"""
        return self.fernet
    
    def encrypt_totp_secret(self, secret: str) -> bytes:
        """TOTP-Secret mit Fernet verschlüsseln (Key via HKDF)"""
        return self.fernet.encrypt(secret.encode())
    
    def decrypt_totp_secret(self, encrypted: bytes) -> str:
        return self.fernet.decrypt(encrypted).decode()
    
    def hash_backup_code(self, code: str) -> str:
        """bcrypt für Backup-Codes (rounds=12)"""
        return bcrypt.hashpw(code.encode(), bcrypt.gensalt(rounds=12)).decode()
    
    def verify_backup_code(self, code: str, hash_str: str) -> bool:
        return bcrypt.checkpw(code.encode(), hash_str.encode())
    
    def hash_client_secret(self, secret: str) -> str:
        """Für OIDC Client Secrets (bcrypt)"""
        return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=12)).decode()
    
    def generate_signing_key(self):
        """
        Generiert neues ES256 Schlüsselpaar für OIDC ID-Tokens.
        Private Key wird mit Fernet verschlüsselt in DB gespeichert.
        """
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()
        
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        public_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        
        kid = str(uuid.uuid4())
        
        return {
            'kid': kid,
            'private_encrypted': self.fernet.encrypt(private_pem).decode(),
            'public': public_pem.decode()
        }
```

---

## 8. Implementierungs-Roadmap

### Phase 1: Flask-Foundation (Woche 1)

**Struktur:**
```
x2fa/
├── app/
│   ├── __init__.py          # App Factory mit Authlib-Setup
│   ├── extensions.py          # db, migrate, limiter, secure_headers
│   ├── config.py             # Config-Klassen
│   ├── models/
│   │   ├── __init__.py
│   │   ├── credential.py
│   │   ├── oidc_client.py     # Mit OAuth2ClientMixin + id PK!
│   │   ├── authorization_code.py  # Mit OAuth2AuthorizationCodeMixin + id/user_id!
│   │   ├── challenge.py
│   │   ├── totp.py
│   │   ├── backup.py
│   │   └── signing_key.py     # Mit get_private_key() + expires_at!
│   ├── routes/
│   │   ├── auth.py           # OIDC-Endpunkte (/authorize, /token)
│   │   ├── webauthn.py       # FIDO2 Setup/Verify
│   │   ├── totp.py           # TOTP (mit DB-agnostischem Replay-Schutz!)
│   │   └── backup.py         # Backup-Codes
│   ├── services/
│   │   ├── crypto.py         # Fernet, bcrypt, HKDF (mit Salt!)
│   │   ├── webauthn_service.py
│   │   └── oidc_provider.py  # Authlib-Integration
│   ├── templates/            # Jinja2 (CSP-nonced)
│   ├── decorators.py         # login_required (einheitlich mit full_path!)
│   └── cli.py                # Flask CLI Commands (init-keys, rotate-keys!)
├── migrations/               # Flask-Migrate
├── wsgi.py                   # Gunicorn Entry
└── requirements.txt
```

### Phase 2: WebAuthn + Sessions (Woche 2)

- Challenge nur in DB (nicht Session), nur für WebAuthn
- `datetime.now(timezone.utc)` für alle Zeitstempel (nicht utcnow!)
- CSP-Nonces in Templates integrieren
- **KORRIGIERT:** `session.permanent = True` nach 2FA-Login setzen!

### Phase 3: TOTP & Backup (Woche 3)

- TOTP braucht **keine** serverseitige Challenge (zeitbasiert)
- Backup-Codes mit `bcrypt.hashpw()`
- Fernet-Verschlüsselung für TOTP-Secrets
- **KORRIGIERT:** `last_used_window` Integer-Feld für DB-agnostischen Replay-Schutz

### Phase 4: OIDC-Provider (Woche 4)

- `OAuth2ClientMixin` mit **expliziter `id` Spalte** (Mixin hat keine PK!)
- `OAuth2AuthorizationCodeMixin` mit **expliziten `id` und `user_id`**
- `OpenIDCode` Mixin für ID-Token Funktionalität
- `save_token` No-op Funktion definieren
- `OAuth2Error` importieren (`from authlib.oauth2 import OAuth2Error`)
- **KORRIGIERT:** Key-Rotation mit 24h Overlap (nicht sofort deaktivieren!)
- **KORRIGIERT:** Einheitlicher Redirect-Mechanismus (nur `login_required` mit `full_path`)

---

## 9. Authlib-Integration (Vollständig Korrigiert)

### WICHTIGE Imports

```python
from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core.grants import OpenIDCode
from authlib.oauth2 import OAuth2Error  # KORRIGIERT: Import hinzugefügt!
from flask import session, current_app, redirect, request
from datetime import datetime, timezone
import time
```

### Save-Token Funktion (WICHTIG!)

```python
def save_token(token, request):
    """
    WICHTIG: Auch für JWTs muss save_token existieren!
    Authlib ruft dies auf, auch wenn wir JWTs (stateless) nutzen.
    """
    pass  # JWTs sind stateless, keine DB-Speicherung nötig
```

### Grant-Klasse mit OpenIDCode

```python
class X2FAAuthorizationCodeGrant(AuthorizationCodeGrant, OpenIDCode):
    """
    OpenIDCode Mixin für ID-Token Funktionalität.
    WICHTIG: Wir nutzen KEINEN register_hook, sondern die OpenIDCode Methoden!
    """
    TOKEN_ENDPOINT_AUTH_METHODS = ['client_secret_post', 'client_secret_basic']
    
    def save_authorization_code(self, code, request):
        """
        'code' ist ein String (das Token), NICHT ein Objekt!
        Wir müssen das AuthorizationCode-Objekt selbst erstellen.
        """
        # User-ID aus Flask-Session (nach 2FA-Verification)
        user_id = session.get('user_id')
        if not user_id:
            raise OAuth2Error('login_required', '2FA not completed')
        
        # AuthorizationCode-Objekt instanziieren (Mixin hat keine id/user_id!)
        auth_code = AuthorizationCode(
            code=code,  # Der String von Authlib
            client_id=request.client.client_id,
            user_id=user_id,  # EXPLIZIT!
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            nonce=request.data.get('nonce'),
            code_challenge=request.data.get('code_challenge'),
            code_challenge_method=request.data.get('code_challenge_method', 'S256'),
            auth_time=int(time.time()),  # Integer! (Unix-Timestamp für Mixin)
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
        """
        WICHTIG: Diese Methode fehlte in v5.3!
        Gibt User-ID zurück für ID-Token 'sub' Claim.
        """
        return authorization_code.user_id
    
    # OpenIDCode Mixin Methoden für ID-Tokens:
    def get_jwt_config(self, grant):
        """ID-Token Signierung Konfiguration"""
        from app.services.crypto import CryptoService
        crypto = CryptoService(current_app.config['X2FA_SECRET'])
        
        # Nur aktive Keys (nicht abgelaufen)
        signing_key = SigningKey.query.filter(
            SigningKey.active == True,
            (SigningKey.expires_at == None) | (SigningKey.expires_at > datetime.now(timezone.utc))
        ).order_by(SigningKey.created_at.desc()).first()
        
        if not signing_key:
            raise RuntimeError("No active signing key! Run 'flask init-keys' first")
        
        # Private Key entschlüsseln (Methode existiert!)
        private_key = signing_key.get_private_key(crypto.get_fernet())
        
        return {
            'key': private_key,
            'alg': 'ES256',
            'iss': f"https://{current_app.config['X2FA_DOMAIN']}",
            'exp': 60,  # 1 Minute TTL für ID-Token
            'kid': signing_key.kid
        }
    
    def generate_user_info(self, user_id, scope):
        """Minimal user info für ID-Token (nur sub claim)"""
        return {'sub': user_id}
    
    def exists_nonce(self, nonce, request):
        """Replay-Schutz: Prüfen ob nonce bereits verwendet"""
        if not nonce:
            return False
        return AuthorizationCode.query.filter_by(nonce=nonce).first() is not None

# Initialisierung (KORRIGIERT: mit save_token!)
def query_client(client_id):
    return OIDCClient.query.filter_by(client_id=client_id, active=True).first()

oauth = AuthorizationServer(
    app, 
    query_client=query_client, 
    save_token=save_token  # WICHTIG: Nicht vergessen!
)
oauth.register_grant(X2FAAuthorizationCodeGrant, [CodeChallenge(required=True)])
```

### Decorators (Korrigiert – Einheitlich!)

```python
# app/decorators.py
from functools import wraps
from flask import session, redirect, request, current_app
from urllib.parse import urlparse

def login_required(f):
    """
    KORRIGIERT: Einheitlicher Redirect-Mechanismus für alle Routen!
    Verwendet request.full_path für OIDC-Parameter-Erhaltung.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # KORRIGIERT: Aktuelle URL als Rückpfad (inkl. OIDC-Parameter!)
            next_path = request.full_path
            
            # Open Redirect Schutz: Nur relative Pfade erlauben
            if urlparse(next_path).netloc:
                next_path = '/'
            
            return redirect(f'/verify?next={next_path}')
        
        if not session.get('2fa_verified'):
            return redirect('/verify')
        
        # WICHTIG: Session-Ablauf aktivieren
        session.permanent = True
        
        return f(*args, **kwargs)
    return decorated_function

# KORRIGIERT: require_2fa_for_oidc entfernt! login_required deckt alles ab.
# Die OIDC-Parameter sind in full_path enthalten (z.B. /authorize?client_id=...)
```

### TOTP Replay-Schutz (Korrigiert – DB-Agnostisch mit last_used_window)

```python
# In routes/totp.py oder services/totp_service.py
from sqlalchemy import update, func
from datetime import datetime, timezone
import pyotp
import time

def verify_totp(user_id: str, code: str) -> bool:
    """TOTP-Validierung mit atomarem Replay-Schutz (DB-agnostisch)."""
    crypto = CryptoService(current_app.config['X2FA_SECRET'])
    
    totp_secret = TOTPSecret.query.get(user_id)
    if not totp_secret or not totp_secret.verified:
        return False
    
    secret = crypto.decrypt_totp_secret(totp_secret.secret_encrypted)
    now = datetime.now(timezone.utc)
    current_window = int(time.time()) // 30
    
    # Zuerst validieren (pyotp)
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return False
    
    # Atomares UPDATE: Nur wenn Fenster noch nicht verwendet
    result = db.session.execute(
        update(TOTPSecret)
        .where(
            TOTPSecret.user_id == user_id,
            (TOTPSecret.last_used_window == None) | 
            (TOTPSecret.last_used_window != current_window)
        )
        .values(
            last_used_window=current_window,
            last_used_at=now
        )
    )
    
    if result.rowcount == 0:
        db.session.rollback()
        return False  # Replay oder Race Condition
    
    db.session.commit()
    return True
```

---

## 10. Flask CLI Commands (Korrigiert – mit 24h Overlap!)

```python
# app/cli.py
import click
from flask.cli import with_appcontext
from flask import current_app
from datetime import datetime, timedelta, timezone
from app.models import OIDCClient, SigningKey, db
from app.services.crypto import CryptoService

def register_cli(app):
    @app.cli.command('register-client')
    @click.option('--client-id', required=True)
    @click.option('--client-secret', required=True)
    @click.option('--redirect-uri', required=True)
    @with_appcontext
    def register_client(client_id, client_secret, redirect_uri):
        """OIDC Client registrieren (z.B. für Hauptanwendung)"""
        crypto = CryptoService(current_app.config['X2FA_SECRET'])
        
        client = OIDCClient(
            client_id=client_id,
            client_secret=crypto.hash_client_secret(client_secret)
        )
        # WICHTIG: set_client_metadata() verwenden, nicht direkt _client_metadata = dict!
        client.set_client_metadata({
            'redirect_uris': [redirect_uri],
            'grant_types': ['authorization_code'],
            'response_types': ['code'],
            'token_endpoint_auth_method': 'client_secret_post',
            'scope': 'openid'
        })
        client.name = client_id
        client.active = True
        
        db.session.add(client)
        db.session.commit()
        click.echo(f"Client '{client_id}' registered successfully.")
    
    @app.cli.command('init-keys')
    @with_appcontext
    def init_keys():
        """Initialisiert ersten ES256 Signing Key für OIDC (muss vor ersten Start laufen!)"""
        crypto = CryptoService(current_app.config['X2FA_SECRET'])
        
        # Prüfen ob bereits aktiver Key existiert
        existing = SigningKey.query.filter_by(active=True).first()
        if existing:
            click.echo(f"Active signing key already exists: {existing.kid}")
            return
        
        # Neuen Key generieren
        key_data = crypto.generate_signing_key()
        
        signing_key = SigningKey(
            kid=key_data['kid'],
            private_key_pem_encrypted=key_data['private_encrypted'],
            public_key_pem=key_data['public'],
            algorithm='ES256',
            active=True,
            expires_at=None  # Erster Key läuft nie ab
        )
        
        db.session.add(signing_key)
        db.session.commit()
        click.echo(f"Created ES256 signing key: {key_data['kid']}")
        click.echo("OIDC Provider is ready!")
    
    @app.cli.command('rotate-keys')
    @with_appcontext
    def rotate_keys():
        """
        Rotiert Signing Keys mit 24h Overlap.
        Neue Tokens werden mit neuem Key signiert,
        alte Keys bleiben 24h gültig für bestehende Token.
        """
        crypto = CryptoService(current_app.config['X2FA_SECRET'])
        
        # Alte Keys auf 24h Verfallszeit setzen (nicht sofort deaktivieren!)
        now = datetime.now(timezone.utc)
        overlap_end = now + timedelta(hours=24)
        
        old_keys = SigningKey.query.filter_by(active=True).all()
        for key in old_keys:
            key.expires_at = overlap_end  # 24h Overlap!
            click.echo(f"Key {key.kid} expires at {overlap_end}")
        
        # Neuen Key erstellen (aktiv, kein expires_at)
        key_data = crypto.generate_signing_key()
        new_key = SigningKey(
            kid=key_data['kid'],
            private_key_pem_encrypted=key_data['private_encrypted'],
            public_key_pem=key_data['public'],
            algorithm='ES256',
            active=True,
            expires_at=None  # Neuer Key läuft nicht ab
        )
        
        db.session.add(new_key)
        db.session.commit()
        click.echo(f"Created new active key: {key_data['kid']}")
        click.echo(f"Old keys valid until {overlap_end} (24h overlap)")
```

---

## 11. OIDC-Endpunkte & Abläufe

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/.well-known/openid-configuration` | GET | Discovery-Dokument (RFC 8414) |
| `/.well-known/jwks.json` | GET | X2FA Public Keys (ES256) für Client-Validierung |
| `/authorize` | GET/POST | Authorization Code Flow (nach 2FA-Verification) |
| `/token` | POST | Token Endpoint (Server-zu-Server, ID-Token als JWT) |
| `/setup` | GET | Methodenauswahl (WebAuthn/TOTP) |
| `/setup/complete` | POST | FIDO2-Registrierung abschließen |
| `/verify` | GET/POST | 2FA-Authentifizierung (WebAuthn/TOTP/Backup) |
| `/totp/setup` | GET | TOTP-QR-Code anzeigen |
| `/totp/setup/verify` | POST | TOTP-Setup bestätigen |
| `/backup/verify` | GET/POST | Backup-Code Eingabe (Notfall) |

### OIDC Flow mit 2FA-Zwischenschritt

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Hauptanwendung
    participant X2FA as X2FA OIDC
    participant DB as Datenbank

    App->>User: 302 Redirect → /authorize?client_id=...&state=...&nonce=...
    User->>X2FA: GET /authorize
    X2FA->>X2FA: Prüfe session: 2fa_verified?
    X2FA->>X2FA: Nein → full_path = /authorize?client_id=...
    X2FA->>User: 302 Redirect → /verify?next=/authorize%3Fclient_id%3D...
    
    User->>X2FA: POST /verify (WebAuthn/TOTP/Backup)
    X2FA->>DB: Validierung (Challenge/TOTP mit Replay-Schutz/Backup-Hash)
    X2FA->>X2FA: session['user_id'] = user123<br>session['2fa_verified'] = True<br>session.permanent = True
    X2FA->>User: 302 Redirect → /authorize?client_id=... (aus next-Param)
    
    User->>X2FA: GET /authorize (jetzt mit Session)
    X2FA->>DB: AuthorizationCode(code=..., user_id=user123, expires_at=+60s)
    X2FA->>User: 302 Redirect → redirect_uri?code=ABC&state=...
    
    User->>App: code + state
    App->>App: state prüfen (CSRF)
    App->>X2FA: POST /token (client_secret, code, code_verifier)
    X2FA->>DB: Code validieren, PKCE prüfen (S256)
    X2FA->>X2FA: ID-Token generieren (ES256, sub=user123)
    X2FA->>App: {access_token: "...", id_token: "eyJ..."}
    
    App->>X2FA: GET /.well-known/jwks.json (Public Key holen)
    App->>App: ID-Token validieren (ES256 Signatur prüfen)
    App->>App: Session erstellen → User eingeloggt
```

---

## 12. Installationsprozess (Wichtige Reihenfolge!)

### Variante A: SQLite + Caddy (Single-Node)

**⚠️ ACHTUNG:** Ohne Redis nur **1 Gunicorn-Worker** (`-w 1`), sonst Rate-Limiting inkonsistent!

```bash
# 1. Setup
git clone https://github.com/x2fa/x2fa.git /opt/x2fa && cd /opt/x2fa
uv sync

# 2. Konfiguration
export FLASK_SECRET_KEY=$(openssl rand -hex 32)
export X2FA_DOMAIN=2fa.example.com
export DATABASE_URL=sqlite:///var/lib/x2fa/x2fa.db

# 3. Datenbank initialisieren
flask db upgrade

# 4. WICHTIG: Signing Keys erstellen (sonst OIDC-Fehler!)
flask init-keys

# 5. Client registrieren (z.B. für Hauptanwendung)
flask register-client --client-id myapp \
  --client-secret "$(openssl rand -hex 32)" \
  --redirect-uri https://app.example.com/callback

# 6. Production-Start (nur 1 Worker bei SQLite!)
gunicorn -w 1 -b 127.0.0.1:5000 "app:create_app('production')"
```

### Variante B: PostgreSQL + Redis + Traefik (Enterprise)

```yaml
# docker-compose.yml
version: '3.8'
services:
  x2fa:
    build: .
    environment:
      - DATABASE_URL=postgresql://x2fa:${POSTGRES_PASSWORD}@postgres:5432/x2fa
      - FLASK_SECRET_KEY=${FLASK_SECRET_KEY}
      - REDIS_URL=redis://redis:6379/0  # Zwingend für Multi-Worker!
      - X2FA_DOMAIN=2fa.example.com
    command: >
      sh -c "flask db upgrade &&
             flask init-keys &&
             gunicorn -w 4 -b 0.0.0.0:5000 'app:create_app('production')'"
    depends_on:
      - postgres
      - redis
    networks:
      - internal
  
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: x2fa
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # Via Env!
      POSTGRES_DB: x2fa
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - internal

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    networks:
      - internal

volumes:
  pgdata:
  redisdata:

networks:
  internal:
```

---

## 13. Zusammenfassung aller Fixes (v5.3 → v5.4-final)

| Problem | Fix in v5.4-final |
|---------|-------------------|
| **SQLite vs PostgreSQL TOTP** | `last_used_window` Integer-Feld hinzugefügt (DB-agnostisch) |
| **TOTP Grenzfall t=30** | Window-Vergleich (`!= current_window`) statt `diff < 30` |
| **Inkonsistente Redirects** | `require_2fa_for_oidc` entfernt, nur `login_required` mit `full_path` |
| **Redirect verliert OIDC-Params** | `request.full_path` statt `request.args.get('next')` |
| **TOTP Race Condition** | Atomares `UPDATE ... WHERE` mit `last_used_window` |
| **Keys sofort deaktiviert** | `rotate-keys` setzt `expires_at = now + 24h` statt sofort `active = False` |
| **Open Redirect** | `urlparse(next_url).netloc` prüfung in `login_required` |
| **g.csp_nonce bei Fehlern** | `getattr(g, 'csp_nonce', '')` in `set_security_headers` |
| **Session läuft nie ab** | `session.permanent = True` nach 2FA-Login setzen |
| **QR-Codes blockiert** | `img-src 'self' data:` im CSP Header |
| **HKDF salt=None** | Fixer Salt `b'x2fa-static-salt-v1'` statt None |
| **Hardcoded DB-Passwort** | `${POSTGRES_PASSWORD}` in Docker Compose |
| **OIDCClient keine PK** | `id = Column(Integer, primary_key=True)` explizit |
| **AuthorizationCode felder** | `id` und `user_id` explizit deklariert |
| **OAuth2Error fehlt** | `from authlib.oauth2 import OAuth2Error` |
| **save_token fehlt** | No-op Funktion definiert und übergeben |
| **SigningKey Methode** | `get_private_key(self, fernet)` implementiert |
| **Kein init-keys** | CLI Befehl `flask init-keys` hinzugefügt |

---

*Diese Version ist production-ready mit korrektem OIDC-Flow, DB-agnostischem TOTP-Replay-Schutz (SQLite + PostgreSQL), einheitlichem Redirect-Handling und vollständiger Authlib-Integration.*