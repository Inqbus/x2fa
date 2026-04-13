# X2FA Architektur v2.0
**FIDO2 Microservice mit OIDC-Provider – Produktionsreife Authlib-Integration**
*Stand: 2026-04-13*

---

## 1. Vision & Value Proposition

X2FA ist ein standalone 2FA-Microservice mit vollständigem OIDC-Provider (OpenID Connect), der in bestehende Anwendungen über den standardisierten Authorization Code Flow integriert wird. Unterstützt alle FIDO2-Authenticator-Klassen (Platform, Roaming, Hybrid) sowie TOTP-Fallback für universelle Plattformkompatibilität (inkl. Linux).

**Value Proposition:** FIDO2-Authentifizierung ohne Framework-Overhead, datenbankagnostisch, mit intelligenter Fallback-Strategie für alle Plattformen (macOS, Windows, Linux, iOS, Android). Kommunikation über OIDC-Standard – keine proprietären JWTs, keine geteilten Secrets zwischen App und X2FA.

### Bring Your Own Domain + Bring Your Own Infrastructure

| Komponente | Nutzer bringt | X2FA stellt bereit |
|------------|---------------|-------------------|
| **Domain** | DNS A-Record (`2fa.example.com` → Server-IP) | Automatische RP-ID Konfiguration |
| **TLS/Infrastruktur** | Caddy/nginx/Traefik/Cloudflare | HTTP-Backend auf localhost:5000 |
| **Datenbank** | SQLite (Default), PostgreSQL oder MySQL | SQLAlchemy-ORM mit Migrationen |
| **Authenticator** | FaceID/TouchID (Apple), Hello (Windows), Android Biometrie, YubiKey (USB/NFC), Phone-as-Key (Hybrid) | Auto-Detection der verfügbaren Methoden, Cross-Platform Support |
| **Fallback** | TOTP-App (Google Authenticator o.ä.) | Verschlüsselte Speicherung (Fernet) |
| **Notfall** | 10 Backup-Codes | Einmalige Validierung |
| **Integration** | OIDC-Client (client_id + client_secret) | OIDC Authorization Code Flow, JWKS-Endpunkt, Discovery |

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
    subgraph "CLIENT"
        Browser["Browser<br/>Vanilla JS inline"]
        PlatformAuth["Platform Authenticator<br/>FaceID / TouchID / Windows Hello"]
        RoamingAuth["Roaming Authenticator<br/>YubiKey USB/NFC"]
        HybridAuth["Hybrid/Phone<br/>Android/iPhone via QR/BLE"]
        TOTPApp["TOTP-App<br/>Google Authenticator o.ä."]
    end

    subgraph "INFRASTRUKTUR"
        TLS["HTTPS Terminierung<br/>Caddy / nginx / Traefik / Cloudflare"]
    end

    subgraph "X2FA SERVICE"
        Flask["Flask 3.1+<br/>HTTP localhost:5000"]

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

    MainApp <-->|"OIDC Authorization Code Flow"| TLS

    style PlatformAuth fill:#f9f
    style RoamingAuth fill:#f9f
    style HybridAuth fill:#f9f
    style Flask fill:#ff9
    style SQLAlchemy fill:#bbf
    style SQLite fill:#fbb
```

### HTTPS-Strategien (Resolveragnostisch)

| Setup | Verwendung | Konfiguration |
|-------|-----------|---------------|
| **Caddy** | Zero-Config, Auto-HTTPS | `reverse_proxy localhost:5000`, automatische Zertifikate |
| **nginx** | Enterprise, manuelle Kontrolle | `proxy_pass http://127.0.0.1:5000`, Certbot-Integration |
| **Traefik** | Docker/Cloud-Native | Label-basierte Discovery, Auto-HTTPS |
| **Cloudflare Tunnel** | Serverless/Home-Lab | Edge-Terminierung, intern HTTP |

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
| **Krypto** | cryptography | 46.0.7+, Fernet (AES-128-CBC + HMAC-SHA256) |
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

    # Disable Authlib HTTPS requirement in testing
    if cfg.x2fa.TESTING:
        os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

    # Startup-Check: SECRET_KEY muss gesetzt sein
    if 'SECRET_KEY' not in app.config.x2fa_security:
        raise RuntimeError("SECRET_KEY not set in secret_config.toml!")
    app.config['SECRET_KEY'] = app.config.x2fa_security.SECRET_KEY

    # Startup-Check: Redis in Production erforderlich
    if not cfg.x2fa.TESTING and not "RATELIMIT_STORAGE_URI" in app.config.x2fa_ratelimit:
        raise RuntimeError(
            "REDIS_URL must be set in production (distributed rate-limiting)."
        )

    # X2FA_ORIGIN ableiten, falls nicht explizit gesetzt
    if 'ORIGIN' not in app.config.x2fa:
        app.config.x2fa.ORIGIN = f"https://{app.config.x2fa.DOMAIN}"
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

## 5. Authlib-Integration (PKCE S256-Enforcement)

### Grant-Klasse

```python
# src/x2fa/oidc/grants.py
from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core.grants import OpenIDCode

class X2FAAuthorizationCodeGrant(AuthorizationCodeGrant, OpenIDCode):
    """
    OpenIDCode Mixin für ID-Token Funktionalität.
    PKCE S256 erzwungen, plain explizit blockiert.
    """
    TOKEN_ENDPOINT_AUTH_METHODS = ['client_secret_post', 'client_secret_basic']

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
            nonce=request.data.get('nonce'),        # Optional (OIDC Core §3.1.2.1)
            code_challenge=request.data.get('code_challenge'),
            code_challenge_method='S256',           # Hardcoded S256
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
| `/token` | 20/min | Server-zu-Server, kein Browser |
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

### Model `Credential` (FIDO2)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `credential_id` | `LargeBinary`, PK | Base64URL-decodierter FIDO2-Credential-ID |
| `user_id` | `String(255)`, Index | |
| `public_key` | `LargeBinary` | COSE-Key |
| `sign_count` | `Integer`, default=0 | Replay-Schutz |
| `authenticator_type` | `String(20)` | `'platform'` / `'roaming'` |
| `device_type` | `String(20)` | `'single_device'` / `'multi_device'` |
| `transport` | `String(50)`, default=`""` | `usb` / `nfc` / `ble` / `hybrid` / `internal` / `""` (nicht gemeldet) |
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

### Model `OIDCClient` (Registrierte Relying Parties)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `client_id` | `String(255)`, PK | z.B. `shop.example.com` |
| `client_secret` | `String(255)` | Klartext, `secrets.compare_digest` für Vergleich |
| `redirect_uris` | `Text` | Zeilengetrennte URIs; exakter String-Match |
| `allowed_scopes` | `String(255)` | Default: `"openid app:setup"` |
| `active` | `Boolean`, default=True | Revocation |
| `created_at` | `DateTime` | |

### Model `AuthorizationCode` (Kurzlebig, 60s TTL)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | `Integer`, PK, autoincrement | |
| `code` | `String(255)`, Unique, Index | `secrets.token_urlsafe(32)` |
| `client_id` | `String(255)` | |
| `user_id` | `String(255)` | |
| `redirect_uri` | `Text` | Muss mit Request übereinstimmen |
| `scope` | `String(255)` | z.B. `openid app:setup` |
| `nonce` | `String(255)`, nullable | Optional (OIDC Core §3.1.2.1); `None` unterdrückt nonce-Claim |
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
| **Browser** | Challenge, Assertion, TOTP-Codes | CSP `default-src 'none'; script-src 'nonce-{random}';`, Inline-JS only |
| **Flask Backend** | Public Keys, verschlüsselte Secrets | SQLAlchemy ORM (SQL-Injection-Schutz), Fernet-Verschlüsselung vor DB-Schreiben |
| **Transport** | JWTs, WebAuthn-Daten | TLS 1.3 (extern terminiert), HSTS Pflicht |

### Sicherheitsmaßnahmen

1. **CSP-Header:**
   `Content-Security-Policy: default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; form-action https:; base-uri 'none'; frame-ancestors 'none';`
   Der Nonce wird per-Request generiert.

2. **HSTS:**
   `Strict-Transport-Security: max-age=31536000; includeSubDomains` — Pflicht, verhindert SSL-Stripping.

3. **TOTP-Verschlüsselung:** Fernet mit Key aus `SHA256(SECRET_KEY)`. Secret wird als Klartext-Base32 generiert, vor DB-Speicherung verschlüsselt, nur im RAM entschlüsselt.

4. **TOTP-Replay:** `last_used_at` prüfen. Identischer Code im selben 30s-Fenster wird abgelehnt. `NEVER_USED`-Sentinel (1970-01-01) bei Erstverwendung stellt sicher, dass das Prüffenster nie fälschlicherweise auslöst.

5. **Rate-Limiting** — IP-basiert, moving-window, für alle sicherheitskritischen Endpunkte (siehe Section 6).

6. **FIDO2-Replay:** Strikte Sign-Count-Inkrementierung. Sinkender oder gleicher Sign-Count = Klonangriff.

7. **PKCE S256 (RFC 7636):** Pflicht für alle Authorization Code Requests. `plain` wird in `save_authorization_code()` explizit abgelehnt. Client sendet `code_challenge = Base64URL(SHA256(code_verifier))` im `/authorize`-Request; `code_verifier` erst beim `/token`-Request.

8. **OIDC-Sicherheit:**
   - Authorization Code: 60s TTL, einmalig, opak (kein JWT)
   - ID-Token: ES256 (asymmetrisch), 60s TTL, optionales `nonce`-Binding gegen Replay
   - `redirect_uri`: exakter String-Match gegen Whitelist (keine Wildcards)
   - `state`-Parameter: CSRF-Schutz (liegt in Verantwortung der Hauptanwendung)
   - `iss`-Claim: Hauptanwendung muss gegen konfigurierte Issuer-URL prüfen
   - Einheitliche Fehlermeldungen bei ungültiger `client_id` oder `redirect_uri` (kein Enumeration-Leak)

9. **OIDC Key-Rotation:**
   - JWKS enthält aktiven Key + ältere Keys im Overlap-Fenster
   - Rotation via CLI: `flask init-keys` (deaktiviert alle bisherigen Keys)
   - `NEVER_EXPIRES`-Sentinel für Keys ohne geplanten Ablauf

10. **Gegenseitige Authentifizierung:**
    - X2FA → Hauptanwendung: ID-Token ES256-signiert; Hauptanwendung verifiziert via `/.well-known/jwks.json`
    - Hauptanwendung → X2FA: `client_id` + `client_secret` (`client_secret_post` oder `client_secret_basic`); Vergleich via `secrets.compare_digest`

11. **DB-Security:** SQLite (0600), PostgreSQL (SSL-Mode require), Prepared Statements via SQLAlchemy ORM.

12. **Backup-Code-Entropie:** `secrets.token_hex(4).upper()` = 8 Hex-Zeichen (32 Bit), bcrypt rounds=12.

13. **IP-Anonymisierung:** `SHA256(ip + SECRET_SALT)` im AuditLog – kein Klartext-IP gespeichert (DSGVO-konform).

---

## 10. OIDC-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/.well-known/openid-configuration` | GET | Discovery-Dokument (RFC 8414) |
| `/.well-known/jwks.json` | GET | X2FA Public Key Set (RFC 7517) |
| `/authorize` | GET | Startet Authorization Code Flow |
| `/token` | POST | Code gegen ID-Token tauschen (server-zu-server) |
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
  "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
  "claims_supported": ["sub", "iss", "aud", "exp", "iat", "nonce"]
}
```

### OIDC Authorization Code Flow

```mermaid
sequenceDiagram
    participant App as Hauptanwendung
    participant Browser as Browser
    participant X2FA as X2FA OIDC-Provider
    participant DB as Datenbank

    App->>App: client_id, state, nonce generieren
    App->>Browser: 302 → /authorize?client_id=...&code_challenge=...&state=...
    Browser->>X2FA: GET /authorize
    X2FA->>X2FA: client_id, redirect_uri, PKCE validieren
    X2FA->>Browser: 2FA-Dialog (WebAuthn / TOTP / Backup)
    Browser->>X2FA: 2FA durchführen
    X2FA->>DB: Authorization Code speichern (60s TTL)
    X2FA->>Browser: 302 → redirect_uri?code=ABC&state=...
    Browser->>App: code + state
    App->>App: state prüfen (CSRF-Schutz)
    App->>X2FA: POST /token (client_id, client_secret, code, code_verifier)
    Note over App,X2FA: Server-zu-Server, kein Browser!
    X2FA->>DB: Code validieren (einmalig, TTL, PKCE, redirect_uri-Match)
    X2FA->>App: ID-Token (ES256-signiert)
    App->>App: ID-Token via /jwks.json verifizieren
    App->>App: nonce, iss, aud, sub prüfen
```

---

## 11. Admin CLI

```bash
# Signing-Key generieren (EC P-256, ES256)
flask init-keys

# OIDC-Client registrieren
flask add-client shop.example.com https://shop.example.com/auth/callback \
  --secret "sicheres-passwort" \
  --scopes "openid app:setup"

# Clients auflisten
flask list-clients

# Client deaktivieren
flask revoke-client shop.example.com

# Audit-Statistiken
flask stats

# Alte Authorization Codes bereinigen (>1h, nonce-sicher)
flask cleanup-codes
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

### Variante A: SQLite (Zero-Config, Entwicklung)

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

# Datenbank und Signing-Key initialisieren
ENV_FOR_DYNACONF=production flask init-keys

# Starten
ENV_FOR_DYNACONF=production gunicorn "x2fa.wsgi:app" --bind 127.0.0.1:5000
```

### Variante B: PostgreSQL + nginx (Enterprise)

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

nginx-Konfiguration:
```nginx
server {
    listen 443 ssl http2;
    server_name 2fa.example.com;
    ssl_certificate     /etc/letsencrypt/live/2fa.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/2fa.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Variante C: Docker + Traefik + PostgreSQL

```yaml
# docker-compose.yml
services:
  x2fa:
    build: .
    environment:
      - ENV_FOR_DYNACONF=production
      - X2FA_SECURITY_SECRET_KEY=${X2FA_SECRET_KEY}
      - X2FA_SECURITY_SECRET_SALT=${X2FA_SECRET_SALT}
      - X2FA_DB_SQLALCHEMY_DATABASE_URI=postgresql://x2fa:password@postgres:5432/x2fa
      - X2FA_RATELIMIT_RATELIMIT_STORAGE_URI=redis://redis:6379/0
      - X2FA_DOMAIN=2fa.example.com
    networks: [web, internal]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.x2fa.rule=Host(`2fa.example.com`)"
      - "traefik.http.routers.x2fa.tls.certresolver=letsencrypt"

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=x2fa
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=x2fa
    volumes: [pgdata:/var/lib/postgresql/data]
    networks: [internal]

  redis:
    image: redis:7-alpine
    networks: [internal]

volumes:
  pgdata:
```

---

## 14. Zusammenfassung der Sicherheits-Fixes (v5.6 → v2.0)

| # | Problem | Schwere | Fix |
|---|---------|---------|-----|
| 1 | **PKCE plain nicht blockiert** | Hoch | `method != 'S256'` check in `save_authorization_code()` |
| 2 | **Rate-Limits zu locker** | Hoch | Dedizierte Limits: TOTP 5/min, Backup 3/min, WebAuthn 10/min |
| 3 | **Nonce-Schutz bricht bei Cleanup** | Mittel | Cleanup nur für Codes >1h alt |
| 4 | **DATABASE_URL Mapping fehlt** | Funktional | `SQLALCHEMY_DATABASE_URI` explizit in `db_config.toml`, `pool_pre_ping=True` |
| 5 | **SECRET_KEY = None möglich** | Funktional | Startup-Check in `config()` mit `RuntimeError` |
| 6 | **fixed-window Burst-Angriffe** | Mittel | `RATELIMIT_STRATEGY = "moving-window"` |
| 7 | **TestingConfig SECRET_KEY reihenfolge-abhängig** | Funktional | Explizites `SECRET_KEY` im `[testing]`-Environment |
| 8 | **Framework-Migration** | Architektur | Bottle → Flask 3.1+ mit Authlib, Dynaconf, Flask-Limiter |
