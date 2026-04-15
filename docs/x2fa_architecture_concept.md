# X2FA Architektur v2.1
**FIDO2 Microservice mit OIDC-Provider – Self-Sovereign Key Architektur**
*Stand: 2026-04-15*

---

## 1. Vision & Value Proposition

X2FA ist ein standalone 2FA-Microservice mit vollständigem OIDC-Provider (OpenID Connect), der in bestehende Anwendungen über den standardisierten Authorization Code Flow integriert wird. Unterstützt alle FIDO2-Authenticator-Klassen (Platform, Roaming, Hybrid) sowie TOTP-Fallback für universelle Plattformkompatibilität (inkl. Linux).

**Value Proposition:** FIDO2-Authentifizierung ohne Framework-Overhead, datenbankagnostisch, mit intelligenter Fallback-Strategie für alle Plattformen (macOS, Windows, Linux, iOS, Android). Kommunikation über OIDC-Standard – keine proprietären JWTs, **keine geteilten Secrets zwischen App und X2FA** (Self-Sovereign Keys via X.509/mTLS).

### Bring Your Own Domain + Bring Your Own Infrastructure

| Komponente | Nutzer bringt | X2FA stellt bereit |
|------------|---------------|-------------------|
| **Domain** | DNS A-Record (`2fa.example.com` → Server-IP) | Automatische RP-ID Konfiguration |
| **TLS/Infrastruktur** | Caddy/nginx/Traefik/Cloudflare | HTTP-Backend auf localhost:5000 |
| **Datenbank** | SQLite (Default), PostgreSQL oder MySQL | SQLAlchemy-ORM mit Migrationen |
| **Authenticator** | FaceID/TouchID (Apple), Hello (Windows), Android Biometrie, YubiKey (USB/NFC), Phone-as-Key (Hybrid) | Auto-Detection der verfügbaren Methoden, Cross-Platform Support |
| **Fallback** | TOTP-App (Google Authenticator o.ä.) | Verschlüsselte Speicherung (Fernet) |
| **Notfall** | 10 Backup-Codes | Einmalige Validierung |
| **Integration** | OIDC-Client (X.509-Zertifikat oder Private Key) | OIDC Authorization Code Flow, JWKS-Endpunkt, Discovery, mTLS |

### Authenticator-Strategie (Cross-Platform)

| Plattform | Primäre Methode | Fallback | Implementierung |
|-----------|----------------|----------|-----------------|
| **macOS/iOS** | Secure Enclave (TouchID/FaceID) | TOTP | `navigator.credentials` ohne Attachment-Filter |
| **Windows 10/11** | TPM 2.0 (Windows Hello) | TOTP | Platform-Detection |
| **Android** | StrongBox/TEE | TOTP | Biometrie-API |
| **Linux Desktop** | Hybrid/Phone-as-Key oder YubiKey | TOTP | QR-Code für Phone-Auth oder USB-Roaming |
| **Server/Headless** | TOTP oder Backup-Codes | – | Kein WebAuthn verfügbar |

Keine `authenticatorAttachment: "platform"` Einschränkung – ermöglicht YubiKey und Hybrid-Transport.

---

## 2. Systemarchitektur

### Komponentendiagramm

```mermaid
graph TB
    subgraph "TRUST ROOT"
        CA["Interne CA<br/>Root-Zertifikat<br/>Trust-Anchor für X2FA"]
    end
    
    subgraph "CLIENT"
        Browser["Browser<br/>Vanilla JS inline"]
        PlatformAuth["Platform Authenticator<br/>FaceID / TouchID / Windows Hello"]
        RoamingAuth["Roaming Authenticator<br/>YubiKey USB/NFC"]
        HybridAuth["Hybrid/Phone<br/>Android/iPhone via QR/BLE"]
        TOTPApp["TOTP-App<br/>Google Authenticator o.ä."]
        
        subgraph "Hauptanwendung"
            App["Flask/Django/Node.js<br/>OIDC Client"]
            Key["Private Key<br/>(lokal, AES-verschlüsselt)"]
            Cert["X.509 Zertifikat<br/>CN=client_id"]
        end
    end

    subgraph "INFRASTRUKTUR"
        TLS["HTTPS Terminierung<br/>Caddy / nginx / Traefik"]
    end

    subgraph "X2FA SERVICE"
        Flask["Flask 3.1+<br/>HTTP localhost:5000"]
        
        subgraph "AUTHENTICATOR"
            MTLS["mTLS-Validation<br/>oder private_key_jwt"]
            TrustedCA["Trusted CA Store<br/>(Root-Certs)"]
        end

        subgraph "DATENBANKSCHICHT"
            SQLAlchemy["SQLAlchemy 2.0+ ORM"]
        end

        subgraph "DATENBANK"
            SQLite[("SQLite Default")]
            Postgres[("PostgreSQL")]
            MySQL[("MySQL")]
        end
    end

    MainApp["HAUPTANWENDUNG"]

    Browser <-->|"HTTPS TLS 1.3"| TLS
    TLS <-->|"HTTP"| Flask
    Flask <-->|"SQL"| SQLAlchemy
    SQLAlchemy <-->|"Engine"| SQLite
    SQLAlchemy <-->|"Engine"| Postgres
    SQLAlchemy <-->|"Engine"| MySQL

    Browser <-->|"WebAuthn API"| PlatformAuth
    Browser <-->|"WebAuthn API"| RoamingAuth
    Browser <-->|"caBLE/QR"| HybridAuth
    Browser -.->|"Manuelle Eingabe"| TOTPApp

    App <-->|"mTLS oder JWT"| TLS
    TLS <-->|"X-Client-Certificate"| Flask
    
    App <-->|"OIDC Authorization Code Flow"| TLS
    
    Flask -->|"verifiziert"| TrustedCA
    TrustedCA -.->|"signiert"| Cert
    CA -.->|"Root Cert"| TrustedCA
    
    style PlatformAuth fill:#f9f
    style RoamingAuth fill:#f9f
    style HybridAuth fill:#f9f
    style Flask fill:#ff9
    style SQLAlchemy fill:#bbf
    style SQLite fill:#fbb
    style TrustedCA fill:#bfb
```

### HTTPS-Strategien (Resolveragnostisch)

| Setup | Verwendung | Konfiguration |
|-------|-----------|---------------|
| **Caddy** | Zero-Config, Auto-HTTPS | `reverse_proxy localhost:5000`, automatische Zertifikate, `tls internal` für interne CA |
| **nginx** | Enterprise, manuelle Kontrolle | `proxy_pass http://127.0.0.1:5000`, `ssl_verify_client optional_no_ca` für mTLS |
| **Traefik** | Docker/Cloud-Native | Label-basierte Discovery, Auto-HTTPS, `tls.options.mtls.clientAuth` |

### Datenbank-Strategien

| Setup | Connection String | Verwendung |
|-------|-------------------|------------|
| **SQLite** | `sqlite:///var/lib/x2fa/db.sqlite` | Default, Zero-Config, Single-Node |
| **PostgreSQL** | `postgresql://user:pass@host/x2fa` | Enterprise, HA-Setups |
| **MySQL** | `mysql+pymysql://user:pass@host/x2fa` | Bestehende Infrastruktur |

---

## 3. Technologie-Stack

| Ebene | Technologie | Version |
|-------|-------------|---------|
| **Framework** | Flask | 3.1.3+ |
| **Python** | CPython | 3.11+ |
| **ORM** | SQLAlchemy | 2.0+, `pool_pre_ping=True` |
| **Migrations** | Alembic (optional) | Für PostgreSQL/MySQL Schema-Updates |
| **WebAuthn** | py_webauthn | 2.7.1+ |
| **TOTP** | pyotp | 2.9+, RFC 6238, ±30s Fenster |
| **QR-Code** | qrcode + Pillow | 8.2+ / 12.2+ |
| **OIDC** | Authlib | 1.6.9+, Authorization Code Flow + PKCE, JWKS, Discovery |
| **Krypto** | cryptography | 46.0.7+, Fernet (AES-128-CBC + HMAC-SHA256), X.509 |
| **Hashing** | bcrypt | 5.0.0+, rounds=12 |
| **Rate Limiting** | Flask-Limiter | 4.1.1+, moving-window |
| **Konfiguration** | Dynaconf | 3.2.13+, TOML-Dateien, Umgebungen |
| **i18n** | flask-babelplus | 2.2.0+, 16 Sprachen |
| **WSGI** | Gunicorn | 25.3.0+ |
| **Frontend** | Vanilla JS | ~50 Zeilen inline, CSP-nonced, keine Build-Tools |

### Dependencies (`pyproject.toml`)

```
flask>=3.1.3
flask-sqlalchemy>=3.1.1
flask-limiter>=4.1.1
secure>=1.0.1
authlib>=1.6.9
gunicorn>=25.3.0
webauthn>=2.7.1
pyotp>=2.9.0
qrcode>=8.2
Pillow>=12.2.0
cryptography>=46.0.7
bcrypt>=5.0.0
redis>=7.4.0
dynaconf>=3.2.13
flask-babelplus>=2.2.0

# Optional:
psycopg2-binary>=2.9.0  # PostgreSQL
pymysql>=1.1.0           # MySQL
```

---

## 4. Konfiguration

### Dynaconf mit TOML-Dateien

Die Konfiguration erfolgt über Dynaconf mit fünf thematisch getrennten TOML-Dateien in `src/x2fa/config_files/`. Jede Datei unterstützt die Environments `[default]`, `[production]`, `[testing]`, `[e2e]`. Environment-Variablen mit dem jeweiligen Präfix überschreiben TOML-Werte.

| Config-Datei | Dynaconf-Namespace | Env-Präfix | Inhalt |
|---|---|---|---|
| `x2fa_config.toml` | `cfg.x2fa` | `X2FA_` | Host, Port, Domain, Testing-Flag |
| `db_config.toml` | `cfg.x2fa_db` | `X2FA_DB_` | `SQLALCHEMY_DATABASE_URI` |
| `security_config.toml` | `cfg.x2fa_security` | `X2FA_SECURITY_` | `SECRET_KEY`, `SECRET_SALT`, Session-Cookie-Settings |
| `ratelimit_config.toml` | `cfg.x2fa_ratelimit` | `X2FA_RATELIMIT_` | Rate-Limit-Werte, Redis-URI, Strategie |
| `babel_config.toml` | `cfg.x2fa_babel` | `X2FA_BABEL_` | Sprach-Einstellungen |

### App-Factory mit Startup-Checks

```python
# src/x2fa/init_app/config.py
def config(app: Flask):
    for key in cfg:
        setattr(app.config, key, AttrDict(dict(cfg[key])))

    # Startup-Check: SECRET_KEY muss gesetzt sein
    if 'SECRET_KEY' not in app.config.x2fa_security:
        raise RuntimeError("SECRET_KEY not set in secret_config.toml!")
    app.config['SECRET_KEY'] = app.config.x2fa_security.SECRET_KEY

    # Startup-Check: Redis in Production erforderlich
    if not cfg.x2fa.ENV_FOR_DYNACONF == "testing" and not "RATELIMIT_STORAGE_URI" in app.config.x2fa_ratelimit:
        raise RuntimeError(
            "REDIS_URL must be set in production (distributed rate-limiting)."
        )
```

### Session-Sicherheit (`security_config.toml`)

```toml
[default]
SESSION_COOKIE_SECURE   = true   # Nur HTTPS
SESSION_COOKIE_HTTPONLY = true   # Kein JS-Zugriff
SESSION_COOKIE_SAMESITE = "Lax"  # CSRF-Schutz
PERMANENT_SESSION_LIFETIME = 600 # 10 Minuten in Sekunden

[testing]
SESSION_COOKIE_SECURE   = false
SESSION_COOKIE_SAMESITE = false
```

---

## 5. Authlib-Integration (Self-Sovereign Keys)

### Grant-Klasse

```python
# src/x2fa/oidc/grants.py
from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core.grants import OpenIDCode
from authlib.oauth2.rfc6749 import OAuth2Error

class X2FAAuthorizationCodeGrant(AuthorizationCodeGrant, OpenIDCode):
    """
    OpenIDCode Mixin für ID-Token Funktionalität.
    PKCE S256 erzwungen, plain explizit blockiert.
    Unterstützt Self-Sovereign Keys: tls_client_auth und private_key_jwt.
    """
    TOKEN_ENDPOINT_AUTH_METHODS = [
        'tls_client_auth',      # X.509 Client-Zertifikat über mTLS
        'private_key_jwt',      # JWT mit x5c Header (Zertifikatskette)
        'none'                  # Für Public Clients (mit PKCE allein)
    ]

    def save_authorization_code(self, code, request):
        # PKCE Method prüfen und erzwingen
        method = request.data.get('code_challenge_method', 'S256')
        if method != 'S256':
            raise OAuth2Error(
                'invalid_request',
                'Only S256 code_challenge_method is supported. Plain is not allowed.'
            )

        user_id = session.get('user_id')
        if not user_id:
            raise OAuth2Error('login_required', '2FA not completed')

        auth_code = AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            user_id=user_id,
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            nonce=request.data.get('nonce'),
            code_challenge=request.data.get('code_challenge'),
            code_challenge_method='S256',
            auth_time=int(time.time()),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60)
        )
        db.session.add(auth_code)
        db.session.commit()
        return auth_code

    def query_authorization_code(self, code, client):
        auth_code = AuthorizationCode.query.filter_by(
            code=code, client_id=client.client_id
        ).first()
        if not auth_code or auth_code.is_expired() or auth_code.used:
            return None
        return auth_code

    def delete_authorization_code(self, authorization_code):
        """Marks code as consumed (not physically deleted — nonce replay protection)."""
        authorization_code.used = True
        db.session.commit()

    def authenticate_user(self, authorization_code):
        return authorization_code.user_id

    def authenticate_client(self, request):
        """
        Client-Authentifizierung ohne Shared Secret.
        Unterstützt tls_client_auth (mTLS) oder private_key_jwt.
        """
        auth_method = request.client_metadata.get('token_endpoint_auth_method', 'tls_client_auth')
        
        if auth_method == 'tls_client_auth':
            return self._authenticate_via_mtls(request)
        elif auth_method == 'private_key_jwt':
            return self._authenticate_via_private_key_jwt(request)
        else:
            raise OAuth2Error('invalid_client', f'Unsupported auth method: {auth_method}')

    def _authenticate_via_mtls(self, request):
        """
        Extrahiert Client-Zertifikat aus dem TLS-Handshake (via Header vom Reverse Proxy).
        Validiert gegen TrustedCA.
        """
        client_cert_pem = request.headers.get('X-Client-Certificate')
        if not client_cert_pem:
            raise OAuth2Error('invalid_client', 'Client certificate required')
        
        for ca in TrustedCA.query.filter_by(active=True).all():
            result = ca.verify_certificate(client_cert_pem)
            if result['valid']:
                client = OIDCClient.query.get(result['client_id'])
                if client and client.active:
                    return client
        
        raise OAuth2Error('invalid_client', 'Certificate not trusted or expired')

    def _authenticate_via_private_key_jwt(self, request):
        """
        Verifiziert client_assertion JWT mit eingebettetem X.509-Zertifikat (x5c).
        """
        import jwt
        from cryptography.x509 import load_pem_x509_certificate
        
        assertion = request.form.get('client_assertion')
        if not assertion:
            raise OAuth2Error('invalid_client', 'Missing client_assertion')
        
        try:
            header = jwt.get_unverified_header(assertion)
            x5c_chain = header.get('x5c')
            if not x5c_chain:
                raise OAuth2Error('invalid_client', 'x5c chain missing in JWT header')
            
            client_cert_pem = f"-----BEGIN CERTIFICATE-----\n{x5c_chain[0]}\n-----END CERTIFICATE-----"
            
            for ca in TrustedCA.query.filter_by(active=True).all():
                result = ca.verify_certificate(client_cert_pem)
                if result['valid']:
                    client = OIDCClient.query.get(result['client_id'])
                    if client and client.active:
                        cert = load_pem_x509_certificate(client_cert_pem.encode())
                        public_key = cert.public_key()
                        
                        jwt.decode(
                            assertion, 
                            public_key, 
                            algorithms=['RS256', 'ES256'],
                            audience=request.url_root + 'token'
                        )
                        return client
            
            raise OAuth2Error('invalid_client', 'Invalid certificate or signature')
            
        except Exception as e:
            raise OAuth2Error('invalid_client', str(e))

    def get_jwt_config(self, grant):
        """ID-Token signing configuration (ES256)."""
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        signing_key = SigningKey.query.filter(
            SigningKey.active == True,
            SigningKey.expires_at > datetime.now(timezone.utc)
        ).order_by(SigningKey.created_at.desc()).first()

        if not signing_key:
            raise RuntimeError("No active signing key! Run 'flask init-keys' first")

        private_key = signing_key.get_private_key(crypto.get_fernet())
        return {
            'key': private_key,
            'alg': 'ES256',
            'iss': f"https://{current_app.config.x2fa.DOMAIN}",
            'exp': 60,
            'kid': signing_key.kid
        }

    def generate_user_info(self, user_id, scope):
        return {'sub': user_id}

    def exists_nonce(self, nonce, request):
        """
        Replay protection: checks whether nonce was already used.
        Cleanup must NOT delete codes younger than 1 hour (see Section 7).
        """
        if not nonce:
            return False
        return AuthorizationCode.query.filter_by(nonce=nonce).first() is not None

# Registration
oauth.register_grant(X2FAAuthorizationCodeGrant, [CodeChallenge(required=True)])
```

---

## 6. Rate-Limiting

### Konfiguration (`ratelimit_config.toml`)

```toml
[default]
RATELIMIT_STORAGE_URI   = "memory://"     # Redis URI in Production setzen
RATELIMIT_STRATEGY      = "moving-window" # Schutz vor Burst-Angriffen an Fenstergrenzen
RATELIMIT_HEADERS_ENABLED = true

RATE_LIMIT_AUTHORIZE      = "10 per minute; 100 per hour"
RATE_LIMIT_TOKEN          = "20 per minute"
RATE_LIMIT_SETUP_COMPLETE = "5 per minute"
RATE_LIMIT_TOTP_SETUP     = "5 per minute; 20 per hour"
RATE_LIMIT_TOTP_VERIFY    = "5 per minute; 20 per hour"
RATE_LIMIT_WEBAUTHN_VERIFY = "10 per minute; 30 per hour"
RATE_LIMIT_BACKUP_VERIFY  = "3 per minute; 10 per hour"

CHALLENGE_TTL_MINUTES = 5
```

### Begründung der Limits

| Endpunkt | Limit | Begründung |
|----------|-------|------------|
| `/authorize` | 10/min, 100/h | OIDC-Einstiegspunkt, moderat |
| `/token` | 20/min | Server-zu-Server, Zertifikatsvalidierung |
| `POST /totp/verify` | 5/min, 20/h | 10⁶ mögliche Codes → striktes Limit nötig |
| `POST /backup/verify` | 3/min, 10/h | 8 Hex-Zeichen = 4 Mrd. Kombinationen → sehr strikt |
| WebAuthn verify | 10/min, 30/h | Replay-resistent durch Signaturen, Limit schützt DB |

In Production muss `RATELIMIT_STORAGE_URI` auf einen Redis-Server zeigen (Distributed Rate-Limiting bei mehreren Workern).

---

## 7. Cleanup-Policy (Nonce-Schutz erhalten)

```python
# src/x2fa/cli.py — flask cleanup-codes
def cleanup_authorization_codes():
    """
    Deletes authorization codes older than 1 hour.
    Codes younger than 1 hour are retained for nonce replay protection:
    the nonce must remain queryable until all ID tokens issued from it expire.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    old_codes = AuthorizationCode.query.filter(
        AuthorizationCode.expires_at < cutoff
    ).all()
    count = len(old_codes)
    for code in old_codes:
        db.session.delete(code)
    db.session.commit()
    return count
```

**Nicht erlaubt** (würde Nonce-Schutz brechen):
```python
# FALSCH: Löscht Codes direkt nach Verwendung oder nach TTL-Ablauf
AuthorizationCode.query.filter(AuthorizationCode.used == True).delete()
AuthorizationCode.query.filter(AuthorizationCode.expires_at < now()).delete()
```

---

## 8. Datenbank-Schema (SQLAlchemy Models)

### Model `TrustedCA`

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | `Integer`, PK, autoincrement | |
| `name` | `String(100)`, unique | Bezeichnung der CA (z.B. "inqbus-internal-ca") |
| `cert_pem` | `Text` | CA Public Key (Root oder Intermediate) |
| `active` | `Boolean`, default=True | Aktiv für Validierung |
| `created_at` | `DateTime` | Erstellungszeitpunkt |
| `expires_at` | `DateTime`, nullable | CA-Ablaufdatum |

Methoden:
- `verify_certificate(client_cert_pem)`: Prüft Signatur, Gültigkeitszeitraum und extrahiert CN als client_id.

### Model `OIDCClient` (Zertifikat-basiert)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `client_id` | `String(255)`, PK | CN aus dem X.509-Zertifikat |
| `token_endpoint_auth_method` | `String(50)` | `tls_client_auth` oder `private_key_jwt` |
| `client_cert_fingerprint` | `String(255)`, nullable | Optional: SHA256-Fingerprint für Pinning |
| `redirect_uris` | `Text` | Zeilengetrennte URIs; exakter String-Match |
| `allowed_scopes` | `String(255)` | Default: `"openid"` |
| `jwks_uri` | `String(255)`, nullable | Für private_key_jwt: JWKS-URL des Clients |
| `active` | `Boolean`, default=True | Revocation |
| `created_at` | `DateTime` | |

### Model `Credential` (FIDO2)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `credential_id` | `LargeBinary`, PK | Base64URL-decodierter FIDO2-Credential-ID |
| `user_id` | `String(255)`, Index | |
| `public_key` | `LargeBinary` | COSE-Key |
| `sign_count` | `Integer`, default=0 | Replay-Schutz |
| `authenticator_type` | `String(20)` | `'platform'` / `'roaming'` |
| `device_type` | `String(20)` | `'single_device'` / `'multi_device'` |
| `transport` | `String(50)`, default=`""` | `usb` / `nfc` / `ble` / `hybrid` / `internal` |
| `is_passkey` | `Boolean`, default=False | Cloud-synchronisiert? |
| `created_at` | `DateTime` | UTC |
| `last_used_at` | `DateTime` | `NEVER_USED`-Sentinel bei Registrierung |

Index: `idx_cred_user_created` auf `(user_id, created_at)`.

### Model `Challenge` (Temporär, 5min TTL)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `challenge_id` | `String(255)`, PK | UUID |
| `user_id` | `String(255)`, Index | |
| `challenge` | `LargeBinary` | 32–64 Bytes |
| `expires_at` | `DateTime`, Index | Auto-Cleanup |
| `used` | `Boolean`, default=False | Einmalverwendung |

### Model `TOTPSecret` (Fernet-verschlüsselt)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `user_id` | `String(255)`, PK | |
| `secret_encrypted` | `LargeBinary` | Fernet(AES-128-CBC + HMAC) |
| `verified` | `Boolean`, default=False | Setup abgeschlossen? |
| `created_at` | `DateTime` | |
| `last_used_at` | `DateTime` | `NEVER_USED`-Sentinel; Replay-Schutz (30s Fenster) |

### Model `BackupCode` (10 pro User, einmalig)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `code_hash` | `String(255)`, PK | bcrypt-Hash (rounds=12) |
| `user_id` | `String(255)`, Index | |
| `used_at` | `DateTime` | `NEVER_USED`-Sentinel = gültig; realer Timestamp = verbraucht |
| `created_at` | `DateTime` | |

### Model `AuthorizationCode` (Kurzlebig, 60s TTL)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | `Integer`, PK, autoincrement | |
| `code` | `String(255)`, Unique, Index | `secrets.token_urlsafe(32)` |
| `client_id` | `String(255)` | |
| `user_id` | `String(255)` | |
| `redirect_uri` | `Text` | Muss mit Request übereinstimmen |
| `scope` | `String(255)` | z.B. `openid` |
| `nonce` | `String(255)`, nullable | Optional (OIDC Core §3.1.2.1) |
| `code_challenge` | `String(255)` | PKCE: SHA256(code_verifier), Base64URL |
| `code_challenge_method` | `String(10)` | Immer `S256` |
| `auth_time` | `Integer` | Unix-Timestamp der 2FA-Verification |
| `expires_at` | `DateTime`, Index | 60 Sekunden TTL |
| `used` | `Boolean`, default=False | Einmalverwendung |

### Model `SigningKey` (EC-Schlüsselpaar für ID-Token)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | `Integer`, PK, autoincrement | |
| `kid` | `String(255)`, Unique | Key-ID (16 Hex-Zeichen) |
| `private_key_encrypted` | `LargeBinary` | Fernet-verschlüsselt mit SECRET_KEY |
| `public_key_pem` | `Text` | Klartext; wird in JWKS veröffentlicht |
| `algorithm` | `String(10)` | `ES256` |
| `active` | `Boolean`, default=True | Key-Rotation |
| `created_at` | `DateTime` | |
| `expires_at` | `DateTime` | `NEVER_EXPIRES`-Sentinel für unbegrenzte Keys |

### Model `AuditLog`

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | `Integer`, PK, autoincrement | |
| `user_id` | `String(255)`, Index | |
| `action` | `String(50)`, Index | `setup` / `verify` / `fail` |
| `method` | `String(50)` | `webauthn_platform` / `webauthn_roaming` / `totp` / `backup` |
| `ip_hash` | `String(64)` | `SHA256(ip + SECRET_SALT)` – kein Klartext gespeichert (DSGVO) |
| `timestamp` | `DateTime`, Index | UTC |

---

## 9. Sicherheitskonzept

### Trust Boundaries

| Zone | Daten | Schutzmaßnahmen |
|------|-------|-----------------|
| **Secure Enclave/TPM/HSM** | Private Keys (FIDO2) | Hardware-verschlüsselt, nie exportierbar |
| **Hauptanwendung** | Client Private Key | Lokal gespeichert (verschlüsseltes Filesystem oder HSM), nie über Netzwerk |
| **Browser** | Challenge, Assertion, TOTP-Codes | CSP `default-src 'none'; script-src 'nonce-{random}';`, Inline-JS only |
| **Flask Backend** | Public Keys, verschlüsselte Secrets | SQLAlchemy ORM, Fernet-Verschlüsselung vor DB-Schreiben |
| **Transport** | JWTs, WebAuthn-Daten | TLS 1.3 (extern terminiert), mTLS für Token-Endpunkt |

### Sicherheitsmaßnahmen

1. **Keine Shared Secrets:** Client-Authentifizierung ausschließlich via X.509-Zertifikate (mTLS) oder private_key_jwt. Keine `client_secret`-Strings in der Datenbank.

2. **Certificate Pinning:** Hauptanwendung validiert X2FA-Zertifikat beim JWKS-Abruf (Hardcoded Fingerprint oder Trust-Store).

3. **CSP-Header:**
   `Content-Security-Policy: default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; form-action https:; base-uri 'none'; frame-ancestors 'none';`

4. **HSTS:**
   `Strict-Transport-Security: max-age=31536000; includeSubDomains` — Pflicht, verhindert SSL-Stripping.

5. **TOTP-Verschlüsselung:** Fernet mit Key aus `SHA256(SECRET_KEY)`.

6. **TOTP-Replay:** `last_used_at` prüfen. Identischer Code im selben 30s-Fenster wird abgelehnt.

7. **Rate-Limiting** — IP-basiert, moving-window, für alle sicherheitskritischen Endpunkte.

8. **FIDO2-Replay:** Strikte Sign-Count-Inkrementierung.

9. **PKCE S256 (RFC 7636):** Pflicht für alle Authorization Code Requests. `plain` explizit abgelehnt.

10. **OIDC-Sicherheit:**
    - Authorization Code: 60s TTL, einmalig
    - ID-Token: ES256, 60s TTL, optionales `nonce`-Binding
    - `redirect_uri`: exakter String-Match
    - `state`-Parameter: CSRF-Schutz (Verantwortung der Hauptanwendung)
    - `iss`-Claim: Hauptanwendung prüft gegen konfigurierte Issuer-URL

11. **Key-Rotation:**
    - JWKS enthält aktiven Key + ältere Keys im Overlap-Fenster
    - Rotation via CLI: `flask init-keys`
    - Client-Zertifikate: 90 Tage Gültigkeit, automatische Renewal-Workflows möglich

12. **DB-Security:** SQLite (0600), PostgreSQL (SSL-Mode require), Prepared Statements.

13. **Backup-Code-Entropie:** `secrets.token_hex(4).upper()` = 8 Hex-Zeichen (32 Bit), bcrypt rounds=12.

14. **IP-Anonymisierung:** `SHA256(ip + SECRET_SALT)` im AuditLog.

---

## 10. OIDC-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/.well-known/openid-configuration` | GET | Discovery-Dokument (RFC 8414) |
| `/.well-known/jwks.json` | GET | X2FA Public Key Set (RFC 7517) |
| `/authorize` | GET | Startet Authorization Code Flow |
| `/token` | POST | Code gegen ID-Token tauschen (mTLS oder private_key_jwt) |
| `/setup` | GET | Methodenauswahl (WebAuthn / TOTP) |
| `/setup/complete` | POST | FIDO2-Registrierung abschließen |
| `/totp/setup` | GET | TOTP-QR-Code anzeigen |
| `/totp/setup/verify` | POST | TOTP-Setup bestätigen |
| `/totp/verify` | GET/POST | TOTP-Code eingeben und verifizieren |
| `/backup/verify` | GET/POST | Backup-Code eingeben und verifizieren |
| `/done` | GET | Demo-Callback (nur für Demo-RP) |

### Discovery-Dokument

```json
{
  "issuer": "https://x2fa.example.com",
  "authorization_endpoint": "https://x2fa.example.com/authorize",
  "token_endpoint": "https://x2fa.example.com/token",
  "jwks_uri": "https://x2fa.example.com/.well-known/jwks.json",
  "response_types_supported": ["code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["ES256"],
  "scopes_supported": ["openid", "app:setup"],
  "token_endpoint_auth_methods_supported": ["tls_client_auth", "private_key_jwt"],
  "tls_client_certificate_bound_access_tokens_supported": true,
  "claims_supported": ["sub", "iss", "aud", "exp", "iat", "nonce"]
}
```

### OIDC Authorization Code Flow (Self-Sovereign)

```mermaid
sequenceDiagram
    participant App as Hauptanwendung
    participant Key as Private Key (lokal)
    participant Cert as X.509 Zertifikat
    participant Browser as Browser
    participant TLS as TLS-Layer (mTLS)
    participant X2FA as X2FA OIDC-Provider
    participant CA as Trusted CA

    App->>App: client_id, state, nonce generieren<br/>+ PKCE (code_verifier, code_challenge)
    App->>Browser: 302 → /authorize?client_id=...&code_challenge=...&state=...
    Browser->>X2FA: GET /authorize
    X2FA->>X2FA: client_id, redirect_uri validieren
    X2FA->>Browser: 2FA-Dialog (WebAuthn / TOTP / Backup)
    Browser->>X2FA: 2FA durchführen
    X2FA->>X2FA: Authorization Code generieren (60s TTL)
    X2FA->>Browser: 302 → redirect_uri?code=ABC&state=...
    Browser->>App: code + state
    App->>App: state prüfen (CSRF-Schutz)
    
    Note over App,X2FA: Token-Request mit mTLS
    
    App->>TLS: POST /token<br/>grant_type=authorization_code<br/>&code=ABC<br/>&code_verifier=...<br/>+ Client-Zertifikat im TLS-Handshake
    TLS->>X2FA: Forward mit X-Client-Certificate Header
    X2FA->>CA: Zertifikat validieren<br/>(Signatur, CN=client_id, Gültigkeit)
    CA->>X2FA: ✅ Gültig
    X2FA->>X2FA: Code validieren (TTL, PKCE, redirect_uri, einmalig)
    X2FA->>App: ID-Token (ES256-signiert)
    
    App->>X2FA: GET /.well-known/jwks.json (TLS + Pinning)
    X2FA->>App: JWKS (OP Public Keys)
    App->>App: ID-Token verifizieren<br/>(nonce, iss, aud, sub, exp)
```

---

## 11. Admin CLI

```bash
# CA-Verwaltung
flask add-ca "inqbus-internal-ca" /path/to/ca_cert.pem
flask list-cas
flask revoke-ca "inqbus-internal-ca"

# Signing-Key generieren (EC P-256, ES256)
flask init-keys

# OIDC-Client registrieren (mit Zertifikat)
flask add-client shop.example.com \
  --method tls_client_auth \
  --redirect-uri "https://shop.example.com/auth/callback" \
  --scopes "openid"

# OIDC-Client für private_key_jwt
flask add-client api.example.com \
  --method private_key_jwt \
  --redirect-uri "https://api.example.com/callback" \
  --jwks-uri "https://api.example.com/.well-known/jwks.json"

# Clients auflisten
flask list-clients

# Client deaktivieren
flask revoke-client shop.example.com

# Audit-Statistiken
flask stats

# Alte Authorization Codes bereinigen (>1h, nonce-sicher)
flask cleanup-codes

# Client-Zertifikat generieren (für Entwickler)
flask issue-client-cert shop.example.com \
  --ca "inqbus-internal-ca" \
  --validity-days 90 \
  --output ./certs/
```

---

## 12. Nutzerperspektive: Abläufe

### Szenario A: macOS/iOS (FaceID/TouchID)
Login Haupt-App → Redirect `2fa.example.com/setup` → iOS-Popup "FaceID verwenden?" → Bestätigung → Gesicht scannt → 10 Backup-Codes angezeigt → Fertig.

### Szenario B: Windows Hello (TPM)
Passwort eingeben → Windows Hello Popup (Fingerabdruck/PIN) → Sensor berühren → Sofortige Weiterleitung.

### Szenario C: Linux Desktop (Hybrid/Phone-as-Key)
Linux-PC ohne TPM → Nach 2FA-Start: QR-Code ("Mit Smartphone scannen") → Android/iPhone Kamera öffnet, scannt QR → FaceID am Phone → PC loggt ein (via caBLE/Cloud-Handshake).

### Szenario D: Linux Desktop (YubiKey)
Linux-PC, YubiKey in USB → "YubiKey berühren" → Goldene Fläche berühren → Signatur erfolgt → Login.

### Szenario E: Legacy-Browser/Headless (TOTP)
Kein WebAuthn verfügbar → Redirect `/totp/verify` → Google Authenticator öffnen, 6-stelligen Code eingeben → Login.

### Szenario F: Geräteverlust (Backup-Codes)
Gerät verloren → Neues Gerät → Link "Backup-Code verwenden" → 8-stelligen Hex-Code eingeben → Login erfolgreich, Code verbraucht (9 verbleibend) → App erzwingt neues 2FA-Setup.

---

## 13. Installationsprozess

### Variante A: SQLite + Caddy (Zero-Config)

```bash
git clone <repo> /opt/x2fa && cd /opt/x2fa
uv sync

# Konfiguration
cat > src/x2fa/config_files/security_config.toml << EOF
[production]
SECRET_KEY  = "$(openssl rand -hex 32)"
SECRET_SALT = "$(openssl rand -hex 16)"
EOF

cat > src/x2fa/config_files/x2fa_config.toml << EOF
[production]
DOMAIN = "2fa.example.com"
TESTING = false
EOF

# Interne CA erstellen und registrieren
openssl req -x509 -newkey rsa:4096 -keyout /etc/x2fa/ca_key.pem \
  -out /etc/x2fa/ca_cert.pem -days 3650 -nodes \
  -subj "/C=DE/O=Inqbus/CN=Inqbus-Internal-CA"
chmod 600 /etc/x2fa/ca_key.pem

ENV_FOR_DYNACONF=production flask add-ca "internal-ca" /etc/x2fa/ca_cert.pem

# Signing-Key initialisieren
ENV_FOR_DYNACONF=production flask init-keys

# Ersten Client registrieren (Beispiel)
ENV_FOR_DYNACONF=production flask add-client "shop.example.com" \
  --method tls_client_auth \
  --redirect-uri "https://shop.example.com/auth/callback"

# Starten
ENV_FOR_DYNACONF=production gunicorn "x2fa.wsgi:app" --bind 127.0.0.1:5000
```

Caddyfile:
```caddy
2fa.example.com {
    reverse_proxy localhost:5000
    tls {
        # Automatische Let's Encrypt Zertifikate
    }
}
```

### Variante B: PostgreSQL + nginx + mTLS (Enterprise)

```bash
# PostgreSQL vorbereiten
sudo -u postgres createdb x2fa && sudo -u postgres createuser x2fa -P

# DB-Config
cat > src/x2fa/config_files/db_config.toml << EOF
[production]
SQLALCHEMY_DATABASE_URI = "postgresql://x2fa:password@localhost/x2fa"
EOF

# Rate-Limiting: Redis für Distributed Setup
cat >> src/x2fa/config_files/ratelimit_config.toml << EOF
[production]
RATELIMIT_STORAGE_URI = "redis://localhost:6379/0"
EOF

uv sync --extra postgres
ENV_FOR_DYNACONF=production flask init-keys
ENV_FOR_DYNACONF=production gunicorn "x2fa.wsgi:app" -w 4 --bind 127.0.0.1:5000
```

nginx-Konfiguration (mit mTLS):
```nginx
server {
    listen 443 ssl http2;
    server_name 2fa.example.com;
    
    ssl_certificate     /etc/letsencrypt/live/2fa.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/2fa.example.com/privkey.pem;
    
    # Client-Zertifikate prüfen
    ssl_verify_client optional;
    ssl_client_certificate /etc/nginx/certs/ca_cert.pem;
    ssl_verify_depth 2;
    
    location /token {
        ssl_verify_client on;  # Muss für Token-Endpunkt
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Client-Certificate $ssl_client_cert;
        proxy_set_header X-Client-Verify $ssl_client_verify;
        proxy_set_header X-Client-DN $ssl_client_s_dn;
    }
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Variante C: Client-Zertifikat generieren

```bash
# Für die Hauptanwendung (shop.example.com)
CLIENT_ID="shop.example.com"

# Private Key und CSR
openssl genrsa -out client_key.pem 2048
openssl req -new -key client_key.pem -out client.csr \
  -subj "/C=DE/O=Inqbus/CN=${CLIENT_ID}"

# CA signiert (am X2FA-Server oder sicherer Offline-CA)
openssl x509 -req -in client.csr -CA /etc/x2fa/ca_cert.pem \
  -CAkey /etc/x2fa/ca_key.pem -CAcreateserial \
  -out client_cert.pem -days 90 -sha256

# Bundle für die App
cat client_key.pem client_cert.pem > client_bundle.pem
chmod 600 client_bundle.pem

# client.csr löschen (sicherheitshalber)
rm client.csr
```

Verwendung in der Hauptanwendung (Python):
```python
import requests

# mTLS
response = requests.post(
    "https://2fa.example.com/token",
    data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "code_verifier": pkce_verifier
    },
    cert=("./client_cert.pem", "./client_key.pem"),
    verify=True  # Server-Zertifikat prüfen
)
```

---

## 14. Zusammenfassung

| Aspekt | Implementierung |
|--------|----------------|
| **Authentifizierung** | Keine Shared Secrets; X.509-Zertifikate (mTLS) oder private_key_jwt |
| **Trust-Anchor** | Interne CA (Root-Zertifikat) in X2FA hinterlegt; Client-Zertifikate signiert von dieser CA |
| **Key-Management** | Automatische Rotation von Client-Zertifikaten (90 Tage) und Signing-Keys |
| **2FA-Methoden** | FIDO2 (Platform, Roaming, Hybrid), TOTP, Backup-Codes |
| **OIDC-Sicherheit** | PKCE S256 enforced, 60s Code-TTL, ES256 ID-Tokens, nonce-Support |
| **Skalierbarkeit** | PostgreSQL/MySQL, Redis für Rate-Limiting, stateless Token-Validierung |