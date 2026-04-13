Hier ist die konsolidierte und korrigierte Projektskizze v4.4, die die Linux-Kompatibilität berücksichtigt:

---

# X2FA Projektskizze v5.0
**FIDO2 Microservice mit OIDC-Provider, Multi-Platform-Support und TOTP-Fallback**
*Stand: 2026-03-30*

---

## 1. Vision & Value Proposition

X2FA ist ein standalone 2FA-Microservice mit vollständigem OIDC-Provider (OpenID Connect), der in bestehende Anwendungen über den standardisierten Authorization Code Flow integriert wird. Unterstützt alle FIDO2-Authenticator-Klassen (Platform, Roaming, Hybrid) sowie TOTP-Fallback für universelle Plattformkompatibilität (inkl. Linux).

**Value Proposition:** X2FA in unter 30 Sekunden installieren – FIDO2-Authentifizierung ohne Framework-Overhead, resolveragnostisch, datenbankagnostisch, mit intelligenter Fallback-Strategie für alle Plattformen (macOS, Windows, Linux, iOS, Android). Kommunikation über OIDC-Standard – keine proprietären JWTs, keine geteilten Secrets zwischen App und X2FA.

---

## 2. Kernkonzept

### Bring Your Own Domain + Bring Your Own Infrastructure

| Komponente | Nutzer bringt | X2FA stellt bereit |
|------------|---------------|-------------------|
| **Domain** | DNS A-Record (`2fa.example.com` → Server-IP) | Automatische RP-ID Konfiguration |
| **TLS/Infrastruktur** | Caddy/nginx/Traefik/Cloudflare | HTTP-Backend auf localhost:5000 |
| **Datenbank** | SQLite (Default), PostgreSQL oder MySQL | SQLAlchemy-ORM mit Migrationen |
| **Authenticator** | **Wählbar:** FaceID/TouchID (Apple), Hello (Windows), Android Biometrie, YubiKey (USB/NFC), oder Phone-as-Key (Hybrid) | Auto-Detection der verfügbaren Methoden, Cross-Platform Support |
| **Fallback** | TOTP-App (Google Authenticator) | Verschlüsselte Speicherung (Fernet) |
| **Notfall** | 10 Backup-Codes | Einmalige Validierung |
| **Integration** | OIDC-Client (client_id + privater Key) | OIDC Authorization Code Flow, JWKS-Endpunkt, Discovery |

### Authenticator-Strategie (Korrigiert für Linux)

| Plattform | Primäre Methode | Fallback | Implementierung |
|-----------|----------------|----------|-----------------|
| **macOS/iOS** | Secure Enclave (TouchID/FaceID) | TOTP | `navigator.credentials` ohne Attachment-Filter |
| **Windows 10/11** | TPM 2.0 (Hello) | TOTP | Platform-Detection |
| **Android** | StrongBox/TEE | TOTP | Biometrie-API |
| **Linux Desktop** | **Hybrid/Phone-as-Key** oder **YubiKey** | TOTP | QR-Code für Phone-Auth oder USB-Roaming |
| **Server/Headless** | TOTP oder Backup-Codes | - | Kein WebAuthn verfügbar |

**Wichtig:** Keine `authenticatorAttachment: "platform"` Einschränkung – verwendet `cross-platform` als Default, um YubiKey und Hybrid zu ermöglichen.

---

## 3. Systemarchitektur

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
        Bottle["Bottle Python<br/>HTTP localhost:5000"]
        
        subgraph "DATENBANKSCHICHT"
            SQLAlchemy["SQLAlchemy ORM"]
        end
        
        subgraph "DATENBANK"
            SQLite[("SQLite Default")]
            Postgres[("PostgreSQL")]
            MySQL[("MySQL")]
        end
    end

    MainApp["HAUPTANWENDUNG"]

    Browser <-->|"HTTPS TLS13"| TLS
    TLS <-->|"HTTP"| Bottle
    Bottle <-->|"SQL"| SQLAlchemy
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
    style Bottle fill:#ff9
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
| **SQLite** | `sqlite:///var/lib/x2fa/x2fa.db` | Default, Zero-Config, Single-Node |
| **PostgreSQL** | `postgresql://user:pass@host/x2fa` | Enterprise, HA-Setups |
| **MySQL** | `mysql+pymysql://user:pass@host/x2fa` | Bestehende Infrastruktur |

---

## 4. Technologie-Stack

| Ebene | Technologie | Spezifikation |
|-------|-------------|---------------|
| **Framework** | Bottle (vendored) | `vendor/bottle.py` (4KB), BSD-Lizenz, keine Dependencies |
| **Python** | 3.11+ | |
| **ORM** | SQLAlchemy 2.0+ | DB-Agnostik, Connection Pooling (`pool_pre_ping=True`) |
| **Migration** | Alembic (Optional) | Für PostgreSQL/MySQL Schema-Updates |
| **WebAuthn** | py_webauthn 2.0+ | Server-seitige FIDO2-Validierung |
| **TOTP** | pyotp 2.9+ | RFC 6238, Zeitfenster ±30s |
| **QR-Code** | qrcode 7.4+ Pillow | PNG/SVG Generierung |
| **Tokens** | PyJWT 2.8+ | ES256 (OIDC ID-Token, asymmetrisch), HS256 intern für TOTP |
| **OIDC** | **Authlib** 1.3+ | Authorization Code Flow + PKCE, JWKS, Discovery — keine Eigenimplementierung |
| **Krypto** | cryptography 41.0+ | Fernet (AES-128-CBC + HMAC-SHA256) für TOTP-Secrets |
| **Hashing** | bcrypt/Argon2 | Backup-Code-Hashes |
| **DB-Drivers** | sqlite3/psycopg2/pymysql | SQLite built-in, andere optional |
| **Frontend** | Vanilla JS | ~50 Zeilen inline, CSP-nonced, keine Build-Tools |

### Dependencies

```
webauthn>=2.0.0
pyotp>=2.9.0
qrcode>=7.4
Pillow>=10.0.0
authlib>=1.3.0        # OIDC-Provider (ersetzt PyJWT für Token-Signierung)
cryptography>=41.0.0  # HKDF, EC-Keys, Fernet
sqlalchemy>=2.0.0
bcrypt>=4.0.0
# Optional: psycopg2-binary>=2.9.0, pymysql>=1.1.0, alembic>=1.12.0
```

---

## 5. Datenbank-Schema (SQLAlchemy Models)

### Model `Credential` (FIDO2)

```python
class Credential(Base):
    __tablename__ = 'credentials'
    
    credential_id = Column(LargeBinary(255), primary_key=True)  # Base64URL-decodiert
    user_id = Column(String(255), nullable=False, index=True)
    public_key = Column(LargeBinary, nullable=False)  # COSE-Key
    sign_count = Column(Integer, default=0)  # Replay-Schutz
    authenticator_type = Column(String(20))  # 'platform', 'roaming', 'hybrid'
    device_type = Column(String(20))  # 'single_device', 'multi_device'
    transport = Column(String(50))  # 'usb', 'nfc', 'ble', 'hybrid', 'internal'
    is_passkey = Column(Boolean, default=False)  # Cloud-synchronisiert?
    created_at = Column(DateTime, server_default=func.now())
    last_used_at = Column(DateTime, nullable=True)
```

**Index:** `Index('idx_cred_user', 'user_id', 'created_at')`

### Model `Challenge` (Temporär, 5min TTL)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `challenge_id` | String(255), PK | UUID |
| `user_id` | String(255), Index | |
| `challenge` | LargeBinary | 32-64 Bytes |
| `expires_at` | DateTime, Index | Auto-Cleanup |
| `used` | Boolean, default=False | Einmalverwendung |

### Model `TOTPSecret` (Fernet-Verschlüsselt)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `user_id` | String(255), PK | |
| `secret_encrypted` | LargeBinary | Fernet(AES-128-CBC + HMAC) |
| `verified` | Boolean, default=False | Setup abgeschlossen? |
| `created_at` | DateTime | |
| `last_used_at` | DateTime, nullable | Replay-Schutz (30s Fenster) |

### Model `BackupCode` (10 pro User, einmalig)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `code_hash` | String(255), PK | bcrypt/Argon2 Hash |
| `user_id` | String(255), Index | |
| `used_at` | DateTime, nullable | NULL = gültig, TIMESTAMP = verbraucht |
| `created_at` | DateTime | |

### Model `OIDCClient` (Registrierte Relying Parties)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `client_id` | String(255), PK | z.B. `shop.example.com` |
| `client_secret_hash` | String(255) | bcrypt-Hash des client_secret |
| `redirect_uris` | Text | JSON-Array erlaubter Redirect-URIs |
| `name` | String(255) | Anzeigename |
| `created_at` | DateTime | |
| `active` | Boolean, default=True | Revocation |

### Model `AuthorizationCode` (Kurzlebig, 60s TTL)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `code` | String(255), PK | `secrets.token_urlsafe(32)` |
| `client_id` | String(255), FK | Welcher Client |
| `user_id` | String(255) | Authentifizierter User |
| `redirect_uri` | String(512) | Muss mit Request übereinstimmen |
| `scope` | String(255) | `openid` |
| `nonce` | String(255), nullable | Replay-Schutz für ID-Token |
| `amr` | String(100) | `webauthn_platform`, `totp` etc. |
| `code_challenge` | String(255) | PKCE: SHA256(code_verifier), Base64URL |
| `code_challenge_method` | String(10) | Immer `S256` |
| `expires_at` | DateTime | 60 Sekunden TTL |
| `used` | Boolean, default=False | Einmalverwendung |

### Model `SigningKey` (X2FA EC-Schlüsselpaar)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `kid` | String(64), PK | Key-ID (UUID) |
| `private_key_pem` | Text | Fernet-verschlüsselt mit X2FA_SECRET |
| `public_key_pem` | Text | Klartext (wird in JWKS veröffentlicht) |
| `algorithm` | String(10) | `ES256` |
| `created_at` | DateTime | |
| `active` | Boolean, default=True | Key-Rotation |

### Model `AuditLog` (Optional)

| Feld | Typ | Beschreibung |
|------|-----|--------------|
| `id` | Integer, PK | Auto-Increment |
| `user_id` | String(255), Index | |
| `action` | String(50) | 'setup', 'verify', 'fail' |
| `method` | String(50) | 'webauthn_platform', 'webauthn_roaming', 'totp', 'backup' |
| `timestamp` | DateTime, default=now | |
| `ip_hash` | String(64) | SHA256 mit Salt (GDPR) |

---

## 6. Sicherheitskonzept

### Trust Boundaries

| Zone | Daten | Schutzmaßnahmen |
|------|-------|-----------------|
| **Secure Enclave/TPM/HSM** | Private Keys (FIDO2) | Hardware-verschlüsselt, nie exportierbar |
| **Browser** | Challenge, Assertion, TOTP-Codes | CSP `default-src 'none'; script-src 'nonce-{random}';`, Inline-JS only |
| **Bottle Backend** | Public Keys, verschlüsselte Secrets | SQLAlchemy ORM (SQL-Injection-Schutz), Fernet-Verschlüsselung vor DB-Schreiben |
| **Transport** | JWTs, WebAuthn-Daten | TLS 1.3 (extern terminiert), HSTS Pflicht (`max-age=31536000; includeSubDomains`) |

### Spezifische Maßnahmen

1. **CSP-Header:** `Content-Security-Policy: default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; form-action https:; base-uri 'none'; frame-ancestors 'none';`

2. **HSTS:** `Strict-Transport-Security: max-age=31536000; includeSubDomains` — Pflicht, nicht optional. Verhindert SSL-Stripping-Angriffe.

3. **TOTP-Verschlüsselung:** Fernet mit Key aus `X2FA_SECRET` via **HKDF** (RFC 5869, SHA256, separates Info-Feld `b"x2fa-totp-v1"`). Kein direktes SHA256 des Secrets — HKDF gewährleistet Key-Separation.

4. **TOTP-Replay:** `last_used_at` prüfen. Identischer Code im selben 30s-Fenster wird abgelehnt.

5. **Rate-Limiting** — IP-basiert für alle sicherheitskritischen Endpunkte:
   - `/token` (Token-Endpoint): max 10 Anfragen/Minute
   - `POST /totp/verify`: max 5 Versuche/Minute
   - `POST /backup/verify`: max 5 Versuche/Minute
   - Implementierung: In-Memory Dict (Single-Node) oder Redis (Multi-Node)

6. **FIDO2-Replay:** Strikte Sign-Count-Inkrementierung. Abweichung = Angriff.

7. **PKCE (RFC 7636):** Pflicht für alle Authorization Code Requests.
   - Client sendet `code_challenge` (SHA256-Hash des `code_verifier`) im `/authorize`-Request
   - `code_verifier` wird erst beim `/token`-Request übertragen
   - Verhindert: Abfangen des Authorization Codes im Browser-Redirect
   - `AuthorizationCode`-Model speichert `code_challenge` und `code_challenge_method`

8. **OIDC-Sicherheit:**
   - Authorization Code: 60s TTL, einmalig, opak (kein JWT im Browser)
   - ID-Token: ES256 (asymmetrisch), 1min TTL, `nonce`-Binding gegen Replay
   - `redirect_uri`: exakter String-Match gegen Whitelist (keine Prefix-Matches, keine Wildcards)
   - `state`-Parameter: CSRF-Schutz (Hauptanwendung verantwortlich)
   - `iss`-Claim: Hauptanwendung muss gegen konfigurierte Issuer-URL prüfen
   - Token-Endpoint: nur server-zu-server; `Sec-Fetch-Site: cross-site` wird abgelehnt
   - Einheitliche Fehlermeldungen bei ungültiger `client_id` oder `redirect_uri` (kein Enumeration-Leak)

9. **OIDC Key-Rotation:**
   - JWKS enthält gleichzeitig aktiven Key + bis zu 2 ältere Keys (Overlap-Fenster: 24h)
   - Rotation via Admin CLI: `x2fa_admin rotate-key`
   - Alter Key bleibt im JWKS bis alle ausgestellten ID-Tokens abgelaufen sind

10. **Gegenseitige Authentifizierung:**
    - X2FA → Hauptanwendung: ID-Token ES256-signiert; Hauptanwendung verifiziert via `/jwks.json` (HTTPS durch öffentliche CA)
    - Hauptanwendung → X2FA: `client_id` + `client_secret` (bcrypt, rounds=12) oder `private_key_jwt` (RFC 7523)
    - Keine geteilten Secrets für Token-Signierung

11. **DB-Security:** SQLite (0600), PostgreSQL (SSL-Mode require), Prepared Statements via SQLAlchemy.

12. **Private Key:** X2FA-Signing-Key HKDF-abgeleitet, Fernet-verschlüsselt in DB, nur im RAM entschlüsselt.

13. **Backup-Code-Entropie:** `secrets.token_hex(5)` = 10 Hex-Zeichen (40 Bit), bcrypt rounds=12.

14. **Secret-Management (Optional):** `X2FA_SECRET` und `client_secret` können aus externen Secret-Stores geladen werden (HashiCorp Vault via `VAULT_ADDR`/`VAULT_TOKEN`, AWS Secrets Manager via boto3). Dokumentiert, nicht implementiert in Basis-Version.

---

## 7. Implementierungs-Roadmap

### Phase 1: Foundation (Woche 1)

**Schritt 1.1: Struktur**
```
x2fa/
├── x2fa.py                 # Hauptanwendung
├── vendor/
│   └── bottle.py            # Vendored Bottle
├── models/
│   ├── __init__.py
│   ├── database.py          # SQLAlchemy Engine/Session
│   └── entities.py          # Alle 4 Models
├── repositories/            # Repository-Pattern
│   ├── credential_repo.py
│   ├── challenge_repo.py
│   ├── totp_repo.py
│   └── backup_repo.py
├── templates/               # Bottle-TPLs
│   ├── setup.tpl
│   ├── verify.tpl
│   ├── totp_setup.tpl
│   ├── totp_verify.tpl
│   └── backup_verify.tpl
├── crypto.py                # Fernet, bcrypt-Utils
├── jwt_utils.py             # JWT-Encode/Decode
└── start.py                 # Bootstrap (--backend flag)
```

**Schritt 1.2: SQLAlchemy-Layer**
```python
# models/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.environ.get('X2FA_DATABASE_URL', 'sqlite:///x2fa.db')

engine = create_engine(
    DATABASE_URL, 
    pool_pre_ping=True,  # Verbindungs-Health-Check
    echo=False
)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    Base.metadata.create_all(bind=engine)
```

**Schritt 1.3: Repository-Pattern**
- `CredentialRepo`: `create()`, `get_by_user()`, `update_sign_count()`, `get_by_credential_id()`
- `ChallengeRepo`: `create()`, `get_valid()`, `mark_used()`, `cleanup_expired()`
- `TOTPRepo`: `create_encrypted()`, `verify_and_update()`, `is_verified()`
- `BackupRepo`: `generate_for_user()`, `verify_and_consume()`, `count_remaining()`

**Schritt 1.4: Krypto-Utils**
- Fernet-Key aus `X2FA_SECRET` via `cryptography.fernet.Fernet`
- bcrypt (oder Argon2) für Backup-Code-Hashes mit automatischem Salt

**Schritt 1.5: JWT-Utils**
- `generate_jwt(payload: dict, expires_in: int = 300) -> str` (HS256)
- `verify_jwt(token: str, expected_action: str = None) -> dict`

**Schritt 1.6: Bootstrap `start.py`**
```python
import argparse
import os
import subprocess

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['caddy', 'nginx', 'traefik', 'none'], default='caddy')
    parser.add_argument('--bind', default='127.0.0.1:5000')
    args = parser.parse_args()
    
    # DB initialisieren
    from models import init_db
    init_db()
    
    if args.backend == 'caddy':
        download_caddy_if_missing()
        generate_caddyfile(args.bind)
        subprocess.Popen(['./caddy', 'run'])
    
    # Bottle starten
    import x2fa
    x2fa.app.run(server='wsgiref', host='127.0.0.1', port=5000)

if __name__ == '__main__':
    main()
```

### Phase 2: WebAuthn Core (Woche 2)

**Schritt 2.1: Setup-Route `GET /setup`**
- JWT validieren
- **Wichtig:** Keine `authenticatorAttachment` Einschränkung (Cross-Platform Default)
- Challenge generieren, in DB speichern
- Template rendern mit Detection-JS: Prüft `PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()` und zeigt entsprechende UI (FaceID-Option vs. "YubiKey einstecken" vs. "Smartphone scannen")

**Schritt 2.2: Setup-Complete `POST /setup/complete`**
- `verify_registration_response()` (py_webauthn)
- `CredentialRepo.create()` mit `transport`, `authenticator_type`, `device_type`
- `BackupRepo.generate_for_user(user_id, count=10)`
- Return-JWT generieren (enthält Backup-Codes im Claim oder zeigt sie im Template an)
- 302 Redirect

**Schritt 2.3: Verify-Route `GET /verify`**
- JWT validieren
- Alle Credentials für User laden (`CredentialRepo.get_by_user()`)
- Challenge generieren, speichern
- Template mit `allowCredentials` (alle registrierten Keys)
- Detection: Falls keine Credentials für diesen Browser (neues Gerät), zeige "Gerät nicht registriert" + Link zu Backup-Codes oder Hybrid-Setup

**Schritt 2.4: Verify-Complete `POST /verify/complete`**
- `verify_authentication_response()`
- Sign-Count prüfen und inkrementieren (Atomar via SQLAlchemy)
- Return-JWT mit `amr` (Authentication Method Reference): `["webauthn_platform"]`, `["webauthn_roaming"]`, oder `["hybrid"]`
- Redirect

### Phase 3: TOTP-Fallback (Woche 3)

**Schritt 3.1: Setup `GET /totp/setup`**
- JWT validieren
- Base32-Secret generieren: `pyotp.random_base32()`
- Fernet-Verschlüsselung: `fernet.encrypt(secret.encode())`
- `TOTPSecretRepo.create_encrypted(user_id, encrypted_bytes)`
- QR-Code: `qrcode.make(f"otpauth://totp/X2FA:{user_id}?secret={secret}&issuer=X2FA")`
- Template: QR-Code als Data-URI + Secret-Text + Eingabefeld

**Schritt 3.2: Setup-Verify `POST /totp/setup/verify`**
- Code aus Formular
- Secret laden, entschlüsseln
- `totp.verify(code, valid_window=1)` (±30s)
- Bei Erfolg: `verified=True` setzen
- Return-JWT

**Schritt 3.3: Verify `GET /totp/verify`**
- Reines HTML-Formular (kein JS nötig)
- Rate-Limiting-Check (IP-basiert)

**Schritt 3.4: Verify-Complete `POST /totp/verify`**
- Code validieren
- `last_used_at` prüfen (Replay-Schutz: Code wurde bereits in diesem Zeitfenster verwendet?)
- `last_used_at` aktualisieren
- Return-JWT mit `amr: ["totp"]`

### Phase 4: Backup-Codes & Hybrid (Woche 4)

**Schritt 4.1: Backup-Code-Generierung**
- In `/setup/complete` nach erfolgreichem FIDO2: 10 Codes generieren (kryptografisch sicher: `secrets.token_urlsafe(6)` oder ähnlich, 8 Zeichen alfanumerisch)
- bcrypt-Hash jedes Codes
- `BackupCodeRepo.create_hashes(user_id, hashes)`
- Anzeige im Template: "Drucken Sie diese Codes aus. Sie werden nicht erneut angezeigt."

**Schritt 4.2: Backup-Verify-Routen**
- `GET /backup/verify`: Eingabefeld
- `POST /backup/verify`: 
  - Code hashen
  - Suche: `SELECT * FROM backup_codes WHERE code_hash = ? AND user_id = ? AND used_at IS NULL`
  - Bei Treffer: `used_at = now()`, Return-JWT mit `amr: ["backup"]`, `remaining_codes: count_remaining()`
  - Redirect zu App

**Schritt 4.3: Hybrid-Transport (caBLE/QR)**
- Erweiterung des Verify-Templates: Falls `authenticator_type` der Credentials "hybrid" oder "cross-platform" ist, zeige "Smartphone verwenden" mit QR-Code an
- Der QR-Code enthält eine temporäre Session-ID für caBLE (WebAuthn Hybrid Transport)
- Der Browser kommuniziert via Bluetooth LE oder Cloud-Handshake mit dem Phone

### Phase 6: OIDC-Provider (Woche 5-6)

**Schritt 6.1: Kryptographie-Infrastruktur**
- EC-Schlüsselpaar (P-256) beim ersten Start generieren
- Private Key Fernet-verschlüsselt in `SigningKey`-Tabelle persistieren
- `GET /.well-known/jwks.json` — Public Key im JWKS-Format (RFC 7517)

**Schritt 6.2: Discovery-Endpunkt**
- `GET /.well-known/openid-configuration` (RFC 8414)
```json
{
  "issuer": "https://x2fa.dev.inqbus.de",
  "authorization_endpoint": "https://x2fa.dev.inqbus.de/authorize",
  "token_endpoint": "https://x2fa.dev.inqbus.de/token",
  "jwks_uri": "https://x2fa.dev.inqbus.de/.well-known/jwks.json",
  "response_types_supported": ["code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["ES256"],
  "scopes_supported": ["openid"],
  "token_endpoint_auth_methods_supported": ["client_secret_post", "private_key_jwt"],
  "claims_supported": ["sub", "iss", "aud", "exp", "iat", "nonce", "amr"]
}
```

**Schritt 6.3: Client-Registrierung (Admin CLI)**
```bash
python x2fa_admin.py register-client \
  --client-id shop.example.com \
  --client-secret "sicheres-passwort" \
  --redirect-uri https://shop.example.com/auth/callback \
  --name "Online-Shop"

python x2fa_admin.py list-clients
python x2fa_admin.py revoke-client shop.example.com
```

**Schritt 6.4: Authorization Endpoint `GET /authorize`**
- Parameter validieren: `client_id`, `redirect_uri` (exakter Whitelist-Match), `response_type=code`, `scope=openid`, `state`, `nonce`
- PKCE: `code_challenge` (Pflicht) + `code_challenge_method=S256` validieren
- Einheitliche Fehler bei ungültiger `client_id` oder `redirect_uri` (kein Enumeration-Leak)
- Bestehende 2FA-UI anzeigen (WebAuthn / TOTP / Backup — unverändert)
- Nach Erfolg: Authorization Code generieren (`secrets.token_urlsafe(32)`), in DB speichern (60s TTL, inkl. `code_challenge`)
- Redirect: `redirect_uri?code=...&state=...`

**Schritt 6.5: Token Endpoint `POST /token`**
- Server-zu-Server (kein Browser-Zugriff)
- `Sec-Fetch-Site: cross-site` ablehnen
- Rate-Limit: max 10 Anfragen/Minute pro IP
- Parameter: `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `client_secret`, `code_verifier`
- Code validieren (TTL, einmalig, redirect_uri-Match)
- PKCE: `SHA256(code_verifier)` muss gespeicherter `code_challenge` entsprechen
- ID-Token erstellen und mit X2FA-Private-Key signieren (ES256):
```json
{
  "iss": "https://x2fa.dev.inqbus.de",
  "sub": "user123",
  "aud": "shop.example.com",
  "exp": 1234567890,
  "iat": 1234567890,
  "nonce": "abc123",
  "amr": ["webauthn_platform"]
}
```

**Schritt 6.6: Bestehenden Redirect-Flow entfernen**
- `return_url`-Parameter entfällt
- `X2FA_SECRET` nur noch für TOTP-Verschlüsselung, nicht mehr für JWT-Signierung

### Phase 5: Enterprise & Hardening (Woche 7)

**Schritt 5.1: Rate Limiting**
```python
# In-Memory Implementierung (für Single-Node)
from collections import defaultdict
import time

attempts = defaultdict(list)  # ip: [timestamp1, timestamp2...]

def is_rate_limited(ip: str, max_attempts: int = 5, window: int = 60) -> bool:
    now = time.time()
    attempts[ip] = [t for t in attempts[ip] if now - t < window]
    if len(attempts[ip]) >= max_attempts:
        return True
    attempts[ip].append(now)
    return False
```

**Schritt 5.2: Audit Logging**
- `AuditLogRepo.log(user_id, action, method, ip_hash)`
- IP-Hashing: `hashlib.sha256(f"{ip}{SECRET_SALT}".encode()).hexdigest()`

**Schritt 5.3: Admin CLI `x2fa_admin.py`**
```bash
# Credentials
python x2fa_admin.py list-credentials user123
python x2fa_admin.py revoke-credential <credential_id>
python x2fa_admin.py reset-totp user123
python x2fa_admin.py generate-backup user123

# OIDC-Clients
python x2fa_admin.py register-client --client-id shop.example.com \
  --client-secret "..." --redirect-uri https://shop.example.com/cb
python x2fa_admin.py list-clients
python x2fa_admin.py revoke-client shop.example.com

# Statistiken
python x2fa_admin.py stats
python x2fa_admin.py audit user123
```

**Schritt 5.4: Alembic-Migrationen (für PostgreSQL/MySQL)**
```bash
alembic init migrations
alembic revision --autogenerate -m "Initial schema"
alembic upgrade head
```

---

## 8. OIDC-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/.well-known/openid-configuration` | GET | Discovery-Dokument (RFC 8414) |
| `/.well-known/jwks.json` | GET | X2FA Public Key (RFC 7517) |
| `/authorize` | GET | Startet Authorization Code Flow |
| `/token` | POST | Code gegen ID-Token tauschen (server-zu-server) |
| `/setup` | GET | Methodenauswahl (WebAuthn / TOTP) |
| `/setup/webauthn` | GET | FIDO2-Registrierung |
| `/setup/complete` | POST | FIDO2-Registrierung abschließen |
| `/totp/setup` | GET | TOTP-QR-Code anzeigen |
| `/totp/setup/verify` | POST | TOTP-Setup bestätigen |
| `/totp/verify` | GET/POST | TOTP-Code eingeben |
| `/backup/verify` | GET/POST | Backup-Code eingeben |

### OIDC Authorization Code Flow

```mermaid
sequenceDiagram
    participant App as Hauptanwendung
    participant Browser as Browser
    participant X2FA as X2FA OIDC-Provider
    participant DB as Datenbank

    App->>App: client_id, state, nonce generieren
    App->>Browser: 302 → /authorize?client_id=...&state=...&nonce=...
    Browser->>X2FA: GET /authorize
    X2FA->>X2FA: client_id, redirect_uri validieren
    X2FA->>Browser: 2FA-Dialog (WebAuthn / TOTP / Backup)
    Browser->>X2FA: 2FA durchführen
    X2FA->>DB: Authorization Code speichern (60s TTL)
    X2FA->>Browser: 302 → redirect_uri?code=ABC&state=...
    Browser->>App: code + state
    App->>App: state prüfen (CSRF-Schutz)
    App->>X2FA: POST /token (client_id, client_secret, code)
    Note over App,X2FA: Server-zu-Server, kein Browser!
    X2FA->>DB: Code validieren (einmalig, TTL, redirect_uri-Match)
    X2FA->>App: ID-Token (ES256-signiert)
    App->>App: ID-Token via /jwks.json verifizieren
    App->>App: nonce, iss, aud, sub prüfen
```

### Gegenseitige Authentifizierung

```
Vertrauen durch öffentliche CA (HTTPS):

  Browser kennt X2FA's Identität:
    → TLS-Zertifikat von Let's Encrypt / Wildcard-Cert
    → Keine private CA nötig

  Hauptanwendung kennt X2FA's Identität:
    → /jwks.json über HTTPS (TLS-Zertifikat beweist Identität)
    → ID-Token ES256-Signatur verifiziert mit diesem Public Key

  X2FA kennt Hauptanwendung's Identität:
    → client_id + client_secret (registriert via Admin CLI)
    → Optional: private_key_jwt (RFC 7523) statt client_secret
```

---

## 9. Nutzerperspektive: Abläufe

### Szenario A: macOS/iOS (FaceID/TouchID)
Login Haupt-App → Redirect `2fa.example.com/setup` → iOS-Popup "FaceID verwenden?" → Doppelklick Seitentaste → Gesicht scannt → 10 Backup-Codes angezeigt → Fertig.

### Szenario B: Windows Hello (TPM)
Passwort eingeben → Windows Hello Popup (Fingerabdruck) → Sensor berühren → Sofortige Weiterleitung → Dashboard.

### Szenario C: Linux Desktop (Hybrid/Phone-as-Key)
Linux-PC ohne TPM → Nach Passwort: QR-Code wird angezeigt ("Mit Smartphone scannen") → Android/iPhone Kamera öffnet, scannt QR → FaceID am Phone → PC loggt ein (via caBLE/Cloud-Handshake).

### Szenario D: Linux Desktop (YubiKey)
Linux-PC, YubiKey in USB → Nach Passwort: "YubiKey berühren" → Goldene Fläche berühren (LED blinkt) → Signatur erfolgt → Login.

### Szenario E: Legacy-Browser/Headless (TOTP)
Altes Android-Tablet → Kein WebAuthn → Auto-Redirect `/totp/verify` → Google Authenticator öffnen, Code eingeben → Login.

### Szenario F: Geräteverlust (Backup-Codes)
iPhone verloren → Neues Gerät → Login Passwort → Link "Backup-Code verwenden" → Code "A1B2C3D4" eingeben (vom Ausdruck) → Login erfolgreich, Code verbraucht (9 verbleibend) → App erzwingt neues 2FA-Setup.

---

## 9. Installationsprozess

### Variante A: SQLite + Caddy (Zero-Config, 30 Sekunden)

```bash
git clone https://github.com/x2fa/x2fa.git /opt/x2fa && cd /opt/x2fa
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cat > .env << EOF
X2FA_SECRET=$(openssl rand -hex 32)
X2FA_DOMAIN=2fa.example.com
X2FA_DATABASE_URL=sqlite:///var/lib/x2fa/x2fa.db
X2FA_BIND=127.0.0.1:5000
EOF

python start.py --backend=caddy
# Caddy lädt Zertifikate, SQLAlchemy erstellt Tabellen automatisch
```

### Variante B: PostgreSQL + nginx (Enterprise)

```bash
# PostgreSQL vorbereiten
sudo -u postgres createdb x2fa && sudo -u postgres createuser x2fa -P

# X2FA
echo "X2FA_DATABASE_URL=postgresql://x2fa:password@localhost/x2fa" >> .env
pip install psycopg2-binary

# Schema initialisieren
python -c "from models import init_db; init_db()"

# nginx config (Beispiel)
sudo tee /etc/nginx/sites-available/x2fa << 'EOF'
server {
    listen 443 ssl http2;
    server_name 2fa.example.com;
    ssl_certificate /etc/letsencrypt/live/2fa.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/2fa.example.com/privkey.pem;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
sudo ln -s /etc/nginx/sites-available/x2fa /etc/nginx/sites-enabled/

# Start
python x2fa.py
```

### Variante C: Docker + Traefik + PostgreSQL

```yaml
# docker-compose.yml
version: '3.8'
services:
  x2fa:
    build: .
    environment:
      - X2FA_DATABASE_URL=postgresql://x2fa:password@postgres:5432/x2fa
      - X2FA_SECRET=${X2FA_SECRET}
      - X2FA_DOMAIN=2fa.example.com
    networks:
      - web
      - internal
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
    volumes:
      - pgdata:/var/lib/postgresql/data
    networks:
      - internal

volumes:
  pgdata:
```

---

## 10. Kommunikationsdiagramme

### 10.1 FIDO2 Setup (Cross-Platform, alle Authenticatoren)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank
    participant Auth as Authenticator<br/>(FaceID/YubiKey/Phone)

    User->>App: Login mit Passwort
    App->>App: 2FA nicht eingerichtet
    App->>App: JWT generieren (sub: user123, action: setup, return_url: ..., exp: +5min)
    App->>User: 302 Redirect → 2fa.example.com/setup?token=JWT

    User->>X2FA: GET /setup?token=JWT
    X2FA->>X2FA: JWT validieren
    X2FA->>X2FA: Challenge generieren (32 Bytes)
    X2FA->>DB: Challenge speichern (expires_at: +5min, used: false)
    
    Note over X2FA: KEINE authenticatorAttachment Einschränkung<br/>(Cross-Platform Default)
    X2FA->>User: HTML + Inline-JS<br/>(CSP-Nonce, Challenge, Detection-JS)

    Note over User: Detection:<br/>- Platform verfügbar? → FaceID Button<br/>- Sonst → "YubiKey einstecken" oder "Smartphone scannen"

    User->>User: navigator.credentials.create()
    User->>Auth: Challenge + RP-ID (2fa.example.com)
    
    Note over Auth: Je nach Authenticator:<br/>- FaceID: Biometrie-Check<br/>- YubiKey: Touch<br/>- Phone: Hybrid/QR
    
    Auth->>Auth: Key-Pair generieren (Private im Hardware)
    Auth->>User: Credential-ID + PublicKey + Attestation + Transport-Info

    User->>X2FA: POST /setup/complete<br/>(credential_id, attestation, transport, token)
    
    X2FA->>DB: Challenge validieren (unused, not expired)
    X2FA->>X2FA: verify_registration_response()
    
    X2FA->>DB: INSERT Credential<br/>(transport: 'usb'|'nfc'|'internal'|'hybrid',<br/>authenticator_type: 'platform'|'roaming')
    
    Note over X2FA: 10 Backup-Codes generieren<br/>bcrypt hashen, speichern
    
    X2FA->>X2FA: Return-JWT<br/>(result: success, amr: ["webauthn_platform"] oder ["webauthn_roaming"])
    
    X2FA->>User: 302 Redirect → app/callback?token=ReturnJWT
    User->>App: Callback empfangen
    App->>User: 2FA aktiv + Backup-Codes anzeigen (einmalig)
```

### 10.2 FIDO2 Verify (Multi-Device)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank
    participant Auth as Authenticator<br/>(Gerät X)

    User->>App: Login mit Passwort
    App->>App: 2FA erforderlich
    App->>App: JWT generieren (sub: user123, action: verify)
    App->>User: 302 Redirect → 2fa.example.com/verify?token=JWT

    User->>X2FA: GET /verify?token=JWT
    X2FA->>DB: SELECT Credentials WHERE user_id=123
    X2FA->>X2FA: Challenge generieren
    X2FA->>DB: Challenge speichern
    
    Note over X2FA: allowCredentials: Alle Keys des Users<br/>(YubiKey, FaceID, Hybrid)
    
    X2FA->>User: HTML + Inline-JS<br/>(challenge, allowCredentials: [{id, type, transports}])

    Note over User: Nutzer wählt/wird gefragt:<br/>- FaceID (wenn verfügbar)<br/>- YubiKey einstecken<br/>- Smartphone scannen (Hybrid)

    User->>User: navigator.credentials.get()
    User->>Auth: Assertion-Request (mit Credential-ID)
    
    Note over Auth: Biometrie/PIN/Touch je nach Gerät
    
    Auth->>Auth: Challenge signieren
    Auth->>User: Assertion

    User->>X2FA: POST /verify/complete<br/>(credential_id, assertion, authenticatorData, signature)
    
    X2FA->>DB: Credential laden (PublicKey + SignCount)
    X2FA->>X2FA: verify_authentication_response()<br/>+ SignCount >= stored?
    
    X2FA->>DB: UPDATE SignCount += 1, last_used_at=now()
    
    X2FA->>X2FA: Return-JWT (verified: true, amr: ["webauthn_platform"] oder ["webauthn_roaming"])
    
    X2FA->>User: 302 Redirect → app/callback
    User->>App: Callback → Session → Dashboard
```

### 10.3 TOTP Setup & Verify (Universal-Fallback)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank
    participant Phone as TOTP-App<br/>(Smartphone)

    Note over User: Szenario: Linux-Desktop<br/>oder alter Browser
    
    User->>App: 2FA einrichten
    App->>App: Detection: Kein WebAuthn verfügbar<br/>oder Nutzer wählt manuelle Methode
    App->>User: Redirect → 2fa.example.com/totp/setup?token=JWT

    User->>X2FA: GET /totp/setup?token=JWT
    X2FA->>X2FA: Base32-Secret generieren (32 random bytes)
    X2FA->>X2FA: Fernet-Verschlüsselung mit X2FA_SECRET
    X2FA->>DB: INSERT TOTPSecret<br/>(user123, encrypted_secret, verified=0)
    
    X2FA->>X2FA: QR-Code generieren<br/>otpauth://totp/X2FA:user123?secret=BASE32&issuer=X2FA
    
    X2FA->>User: HTML (QR-Code + Secret als Text + Eingabefeld)

    User->>Phone: QR scannen oder Secret manuell eingeben
    Phone->>User: 6-stelliger Code (z.B. 123456)

    User->>X2FA: POST /totp/setup/verify (code=123456)
    
    X2FA->>DB: Encrypted Secret laden
    X2FA->>X2FA: Entschlüsseln → Base32
    X2FA->>X2FA: pyotp.TOTP(secret).verify("123456", valid_window=1)
    
    X2FA->>DB: UPDATE verified=1
    X2FA->>User: Redirect → App (success)
    
    Note over User: Später: Login mit TOTP
    
    User->>App: Login
    App->>User: Redirect → /totp/verify
    
    User->>X2FA: GET /totp/verify
    X2FA->>User: Eingabefeld (reines HTML)
    
    User->>Phone: Code lesen (z.B. 654321)
    User->>X2FA: POST /totp/verify (code=654321)
    
    X2FA->>DB: Secret laden + last_used_at prüfen (Replay-Schutz)
    X2FA->>X2FA: Validieren
    X2FA->>DB: last_used_at = now()
    
    X2FA->>User: Return-JWT (verified, amr: ["totp"]) → Redirect
```

### 10.4 Backup-Code Verify (Notfall)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank

    Note over User: Gerät verloren (iPhone mit FaceID)<br/>Neues Gerät hat keinen Key

    User->>App: Login (Passwort)
    App->>User: Redirect → 2fa.example.com/verify

    User->>X2FA: GET /verify
    X2FA->>DB: Suche Credentials für Browser<br/>(keine Treffer - neues Gerät)
    
    X2FA->>User: "Kein FIDO2-Schlüssel für dieses Gerät"<br/>Link: "Backup-Code verwenden"

    User->>X2FA: GET /backup/verify?token=JWT
    X2FA->>User: Eingabefeld: "8-stelliger Backup-Code"

    Note over User: Code vom Ausdruck: A1B2C3D4
    
    User->>X2FA: POST /backup/verify (code=A1B2C3D4)
    
    X2FA->>X2FA: bcrypt(code) mit Salt
    X2FA->>DB: SELECT * FROM backup_codes<br/>WHERE code_hash=HASH<br/>AND user_id=123<br/>AND used_at IS NULL
    
    alt Treffer gefunden
        X2FA->>DB: UPDATE used_at=now()
        X2FA->>X2FA: Return-JWT (verified, amr: ["backup"], remaining: 9)
        X2FA->>User: Redirect → App
        App->>User: "Notfall-Login OK. Bitte SOFORT neues 2FA einrichten."
    else Kein Treffer oder bereits verwendet
        X2FA->>User: 403 "Ungültiger oder bereits verwendeter Code"
    end
```

### 10.5 Hybrid Transport (Phone-as-Key für Linux)

```mermaid
sequenceDiagram
    participant Linux as Linux PC (Browser)
    participant X2FA as X2FA Service
    participant Phone as Smartphone (Chrome/Safari)
    participant Auth as Phone Authenticator<br/>(FaceID/Fingerabdruck)

    Note over Linux: Linux Desktop ohne TPM<br/>oder Nutzer bevorzugt Phone

    Linux->>X2FA: GET /verify (oder /setup)
    X2FA->>Linux: HTML zeigt:<br/>1. "QR-Code scannen mit Smartphone"<br/>2. "Oder YubiKey verwenden"

    Note over Linux,Phone: caBLE (Cloud Assisted BLE)<br/>oder QR-basiert
    
    Linux->>X2FA: Request: "Starte Hybrid Session"
    X2FA->>Linux: QR-Code (enthält Session-ID + Challenge)
    
    Phone->>Linux: Kamera scannt QR
    Phone->>X2FA: Verbindungsaufbau (via Bluetooth oder Cloud-Relay)
    X2FA->>Phone: Challenge übertragen
    
    Phone->>Auth: WebAuthn-Anfrage<br/>(FaceID auf iPhone)
    Auth->>Phone: Assertion signiert
    
    Phone->>X2FA: Assertion übertragen<br/>(via caBLE/Cloud)
    
    X2FA->>X2FA: Validierung wie bei normalem WebAuthn
    X2FA->>Linux: "Authentifiziert" (via WebSocket/SSE oder Polling)
    
    Linux->>X2FA: Redirect/Completion
    X2FA->>Linux: Return-JWT
    Linux->>App: Callback
    
    Note over Linux: PC ist eingeloggt,<br/>Authentifizierung fand auf Phone statt
```