# X2FA Projektskizze v4.3
**Zero-Hardware FIDO2 Microservice mit TOTP-Fallback**  
*Stand: 2026-03-28 23:20*

---

## 1. Vision

X2FA ist ein standalone 2FA-Microservice zur Integration in bestehende Anwendungen über einen Redirect-Flow. Primär FIDO2 via Platform Authenticators (FaceID, TouchID, Windows Hello), mit TOTP-Fallback für Legacy-Browser und 10 einmalige Backup-Codes für Geräteverlust.

**Value Proposition:** X2FA in unter 30 Sekunden installieren – FIDO2-Authentifizierung ohne Hardware-Keys, ohne Framework-Overhead, resolveragnostisch und datenbankagnostisch.

---

## 2. Kernkonzept

### Bring Your Own Domain + Bring Your Own Database

| Komponente | Nutzer bringt | X2FA stellt bereit |
|------------|---------------|-------------------|
| **Domain** | DNS A-Record (`2fa.example.com` → Server-IP) | Automatische RP-ID Konfiguration |
| **TLS/Infrastruktur** | Caddy/nginx/Traefik/Cloudflare | HTTP-Backend auf localhost:5000 |
| **Datenbank** | SQLite (Default), PostgreSQL oder MySQL | SQLAlchemy-ORM mit Migrationen |
| **Primär-Auth** | Platform Authenticator (FaceID, TouchID, TPM) | WebAuthn-UI mit Auto-Detection |
| **Fallback-Auth** | TOTP-App (Google Authenticator) | TOTP-Setup/Verify mit Fernet-Verschlüsselung |
| **Notfall-Auth** | Ausgedruckte Backup-Codes (10 Stück) | Einmalige Validierung |
| **Integration** | 2 HTTP-Endpunkte (Redirect + Callback) | Stateless JWT-Kommunikation |

### Authentifizierungs-Hierarchie

1. **FIDO2 Platform** (Primary): FaceID, TouchID, Windows Hello, Android StrongBox
2. **FIDO2 Passkeys** (Cloud): iCloud Keychain, Google Password Manager
3. **FIDO2 Hybrid**: Phone-as-Key via QR-Code/Bluetooth
4. **FIDO2 Roaming** (Optional): YubiKey, Nitrokey
5. **TOTP** (Fallback): Zeitbasierte 6-stellige Codes
6. **Backup-Codes** (Notfall): 10 einmalig verwendbare 8-stellige Codes

---

## 3. Systemarchitektur

### Komponentendiagramm

```mermaid
graph TB
    subgraph "CLIENT"
        Browser["Browser<br/>Vanilla JS inline"]
        PlatformAuth["Platform Authenticator<br/>FaceID TouchID TPM"]
        TOTPApp["TOTP-App"]
    end

    subgraph "INFRASTRUKTUR"
        TLS["HTTPS Terminierung<br/>Caddy nginx Traefik Cloudflare"]
    end

    subgraph "X2FA SERVICE"
        Bottle["Bottle Python<br/>HTTP localhost5000"]
        
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
    Browser -.->|"Manuelle Eingabe"| TOTPApp
    
    MainApp <-->|"302 Redirect JWT"| TLS
    
    style PlatformAuth fill:#f9f
    style Bottle fill:#ff9
    style SQLAlchemy fill:#bbf
    style SQLite fill:#fbb
```

---

## 4. Technologie-Stack

| Ebene | Technologie | Spezifikation |
|-------|-------------|---------------|
| **Framework** | Bottle (vendored) | Single-File `vendor/bottle.py`, BSD-Lizenz |
| **Python** | 3.11+ | |
| **ORM** | SQLAlchemy 2.0+ | DB-Agnostik, Connection Pooling |
| **Migration** | Alembic (Optional) | Für PostgreSQL/MySQL |
| **WebAuthn** | py_webauthn 2.0+ | Server-seitige FIDO2-Validierung |
| **TOTP** | pyotp 2.9+ | RFC 6238, Zeitfenster ±30s |
| **QR-Code** | qrcode 7.4+ Pillow | PNG/SVG Generierung |
| **Tokens** | PyJWT 2.8+ | HS256 |
| **Krypto** | cryptography 41.0+ | Fernet für TOTP-Secrets |
| **DB-Drivers** | sqlite3/psycopg2/pymysql | |
| **Frontend** | Vanilla JS | ~50 Zeilen, CSP-nonced |

### Dependencies

```
py-webauthn>=2.0.0
pyotp>=2.9.0
qrcode>=7.4
Pillow>=10.0.0
pyjwt>=2.8.0
cryptography>=41.0.0
sqlalchemy>=2.0.0
# Optional: psycopg2-binary>=2.9.0, pymysql>=1.1.0, alembic>=1.12.0
```

---

## 5. Datenbank-Schema (SQLAlchemy Models)

### Model `Credential`

| Feld | SQLAlchemy Typ | Beschreibung |
|------|----------------|--------------|
| `credential_id` | `LargeBinary, PK` | Base64URL-decodiert |
| `user_id` | `String(255), Index` | Fremdschlüssel |
| `public_key` | `LargeBinary` | COSE-Key |
| `sign_count` | `Integer, default=0` | Replay-Schutz |
| `authenticator_type` | `String(20)` | platform/roaming/hybrid |
| `is_passkey` | `Boolean, default=False` | Cloud-synchronisiert |
| `created_at` | `DateTime` | |
| `last_used_at` | `DateTime, nullable` | |

### Model `Challenge`

| Feld | SQLAlchemy Typ | Beschreibung |
|------|----------------|--------------|
| `challenge_id` | `String(255), PK` | UUID |
| `user_id` | `String(255), Index` | |
| `challenge` | `LargeBinary` | 32-64 Bytes |
| `expires_at` | `DateTime, Index` | 5min TTL |
| `used` | `Boolean, default=False` | Einmalig |

### Model `TOTPSecret`

| Feld | SQLAlchemy Typ | Beschreibung |
|------|----------------|--------------|
| `user_id` | `String(255), PK` | |
| `secret_encrypted` | `LargeBinary` | Fernet-verschlüsselt |
| `verified` | `Boolean, default=False` | Setup abgeschlossen |
| `created_at` | `DateTime` | |
| `last_used_at` | `DateTime, nullable` | Replay-Schutz |

### Model `BackupCode`

| Feld | SQLAlchemy Typ | Beschreibung |
|------|----------------|--------------|
| `code_hash` | `String(255), PK` | bcrypt/Argon2 Hash |
| `user_id` | `String(255), Index` | |
| `used_at` | `DateTime, nullable` | NULL = gültig |
| `created_at` | `DateTime` | |

---

## 6. Sicherheitskonzept

### Trust Boundaries

| Zone | Daten | Schutzmaßnahmen |
|------|-------|-----------------|
| **Secure Enclave** | FIDO2 Private Keys | Hardware-verschlüsselt, nie exportierbar |
| **Browser** | Challenge, Assertion | CSP mit unique Nonce pro Request |
| **Bottle Backend** | Public Keys, verschlüsselte Secrets | SQLite 0600, Fernet, keine Secrets in Logs |
| **Transport** | JWTs, WebAuthn-Daten | TLS 1.3 extern terminiert |

### Spezifische Maßnahmen

1. **CSP:** `default-src 'none'; script-src 'nonce-{random}'; form-action https:;`
2. **TOTP-Verschlüsselung:** Fernet mit Key aus `X2FA_SECRET` (vor DB-Speicherung)
3. **TOTP-Replay:** `last_used_at` prüfen (30s Fenster)
4. **Backup-Rate-Limit:** Max 5 Versuche pro Minute
5. **Challenge-Einmaligkeit:** 5-Minuten-TTL, `used`-Flag
6. **FIDO2 Sign-Count:** Strikte Inkrementierung
7. **JWT-Expiry:** Request 5 Minuten, Return 1 Minute

---

## 7. Implementierungs-Roadmap

### Phase 1: Foundation (Woche 1)

**Schritt 1.1:** Projektstruktur mit `vendor/bottle.py`

**Schritt 1.2:** SQLAlchemy-Layer
```python
DATABASE_URL = os.environ.get('X2FA_DATABASE_URL', 'sqlite:///x2fa.db')
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    Base.metadata.create_all(bind=engine)
```

**Schritt 1.3:** SQLAlchemy-Models für alle 4 Tabellen

**Schritt 1.4:** Repository-Pattern: `CredentialRepo`, `ChallengeRepo`, `TOTPRepo`, `BackupRepo`

**Schritt 1.5:** Fernet-Key aus `X2FA_SECRET`, bcrypt für Backup-Codes

**Schritt 1.6:** JWT-Utilities mit HS256

**Schritt 1.7:** Bootstrap `start.py` mit `--backend=caddy|nginx|traefik|none`

### Phase 2: WebAuthn Core (Woche 2)

**Schritt 2.1:** `GET /setup`: JWT validieren, Challenge generieren, Template rendern

**Schritt 2.2:** `POST /setup/complete`: `verify_registration_response()`, Credential speichern, 10 Backup-Codes generieren

**Schritt 2.3:** `GET /verify`: Credentials laden, Challenge generieren, `allowCredentials` bilden

**Schritt 2.4:** `POST /verify/complete`: `verify_authentication_response()`, Sign-Count updaten

### Phase 3: TOTP-Fallback (Woche 3)

**Schritt 3.1:** `GET /totp/setup`: Secret generieren (Base32), Fernet-verschlüsseln, speichern, QR-Code generieren

**Schritt 3.2:** `POST /totp/setup/verify`: Code validieren, `verified=True` setzen

**Schritt 3.3:** `GET /totp/verify`: Template mit Eingabefeld

**Schritt 3.4:** `POST /totp/verify`: Validierung mit Replay-Schutz

**Schritt 3.5:** Auto-Fallback: Detection `!window.PublicKeyCredential` → Redirect zu `/totp/verify`

### Phase 4: Backup-Codes (Woche 4)

**Schritt 4.1:** Integration in `/setup/complete`: 10 Codes generieren, hashen, speichern, einmalig anzeigen

**Schritt 4.2:** `GET /backup/verify`: Eingabefeld

**Schritt 4.3:** `POST /backup/verify`: Hash prüfen, `used_at` setzen, Return-JWT mit `remaining_codes`

**Schritt 4.4:** Error-Templates für 400/401/403/404

### Phase 5: Enterprise (Woche 5-6)

**Schritt 5.1:** Rate Limiting (In-Memory Dict oder Redis)

**Schritt 5.2:** Audit-Logging (Tabelle `audit_log` mit `ip_hash`)

**Schritt 5.3:** Admin CLI `x2fa_admin.py`: list-credentials, revoke-credential, reset-totp, generate-backup, stats

**Schritt 5.4:** Alembic-Migrationen für PostgreSQL/MySQL

---

## 8. Nutzerperspektive: Abläufe

### Szenario A: Ersteinrichtung mit iPhone FaceID
Login Haupt-App → Redirect `2fa.example.com/setup` → iOS-Popup "FaceID verwenden?" → Doppelklick Seitentaste → Gesicht scannt → 10 Backup-Codes angezeigt (Ausdrucken) → Redirect zur App.

### Szenario B: Täglicher Login mit Windows Hello
Passwort eingeben → Redirect `2fa.example.com/verify` → Windows Hello Popup (Finger/Gesicht) → Sensor berühren → Sofortige Weiterleitung → Dashboard (< 2s).

### Szenario C: Login auf altem PC (TOTP-Fallback)
Windows 7 PC → Kein `PublicKeyCredential` → Auto-Redirect `/totp/verify` → Eingabefeld "6-stelliger Code" → Google Authenticator öffnen → Code eingeben → Login erfolgreich.

### Szenario D: Geräteverlust (Backup-Codes)
iPhone verloren → Neues Gerät → Login mit Passwort → Link "Backup-Code verwenden" → Code "A1B2C3D4" eingeben → Login erfolgreich, Code verbraucht → App erzwingt neues 2FA-Setup.

### Szenario E: Cross-Device (Desktop + iPhone als Key)
Desktop ohne Webcam → QR-Code wird angezeigt → iPhone scannt QR → FaceID-Popup → Gesicht scannt → Desktop loggt automatisch ein.

### Szenario F: TOTP-Einrichtung (Legacy-Device)
Altes Android-Tablet → Kein WebAuthn → `/totp/setup` → QR-Code anzeigen → Google Authenticator installieren, QR scannen → Code eingeben → Setup erfolgreich.

---

## 9. Installationsprozess (DB- und Resolveragnostisch)

### Variante A: SQLite + Caddy (Zero-Config)

```bash
git clone https://github.com/x2fa/x2fa.git /opt/x2fa && cd /opt/x2fa
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

echo "X2FA_SECRET=$(openssl rand -hex 32)" > .env
echo "X2FA_DOMAIN=2fa.example.com" >> .env
echo "X2FA_DATABASE_URL=sqlite:///var/lib/x2fa/x2fa.db" >> .env

python start.py --backend=caddy
```

### Variante B: PostgreSQL + nginx (Enterprise)

```bash
# PostgreSQL vorbereiten
sudo -u postgres createdb x2fa
sudo -u postgres createuser x2fa -P

# X2FA
echo "X2FA_DATABASE_URL=postgresql://x2fa:password@localhost/x2fa" >> .env
pip install psycopg2-binary

python -c "from x2fa.models import init_db; init_db()"
# Optional: alembic upgrade head

# nginx konfigurieren (proxy_pass http://127.0.0.1:5000)
python x2fa.py  # oder gunicorn
```

### Variante C: MySQL + Traefik (Docker)

```yaml
# docker-compose.yml
services:
  x2fa:
    image: x2fa
    environment:
      - X2FA_DATABASE_URL=mysql+pymysql://x2fa:password@mysql:3306/x2fa
      - X2FA_DOMAIN=2fa.example.com
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.x2fa.rule=Host(`2fa.example.com`)"
      - "traefik.http.routers.x2fa.tls.certresolver=letsencrypt"
```

---

## 10. Kommunikationsdiagramme

### 10.1 FIDO2 Setup (Ersteinrichtung)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank
    participant Auth as Platform Authenticator

    User->>App: Login mit Passwort
    App->>App: Prüfung 2FA nicht eingerichtet
    App->>App: JWT generieren (sub: user123, action: setup, return_url: https://app/callback, exp: +5min)
    App->>User: 302 Redirect → 2fa.example.com/setup?token=JWT

    User->>X2FA: GET /setup?token=JWT
    X2FA->>X2FA: JWT validieren
    X2FA->>X2FA: Challenge generieren (32 Bytes)
    X2FA->>DB: Challenge speichern (TTL 5min, used=0)
    X2FA->>User: HTTP 200 HTML + Inline-JS (CSP-Nonce, Challenge b64)

    User->>User: navigator.credentials.create()
    User->>Auth: Challenge + RP-ID
    Auth->>Auth: Key-Pair generieren (Private im Secure Enclave)
    Auth->>User: Credential-ID + PublicKey + Attestation

    User->>X2FA: POST /setup/complete (credential_id, attestation, token)
    X2FA->>DB: Challenge laden und validieren
    X2FA->>X2FA: verify_registration_response()
    X2FA->>DB: INSERT credentials (credential_id, public_key, type='platform')
    Note over X2FA: 10 Backup-Codes generieren, hashen, speichern
    X2FA->>X2FA: Return-JWT (result: success, amr: ["face"])
    X2FA->>User: 302 Redirect → app/callback?token=ReturnJWT

    User->>App: GET /callback?token=ReturnJWT
    App->>App: JWT validieren
    App->>User: 2FA aktiv. Backup-Codes ausdrucken.
```

### 10.2 FIDO2 Verify (Login)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank
    participant Auth as Platform Authenticator

    User->>App: Login mit Passwort
    App->>App: 2FA erforderlich
    App->>App: JWT generieren (sub: user123, action: verify)
    App->>User: 302 Redirect → 2fa.example.com/verify?token=JWT

    User->>X2FA: GET /verify?token=JWT
    X2FA->>DB: SELECT credentials WHERE user_id=123
    X2FA->>X2FA: Challenge generieren
    X2FA->>DB: Challenge speichern
    X2FA->>User: HTML + Inline-JS (challenge, allowCredentials)

    User->>User: navigator.credentials.get()
    User->>Auth: Assertion-Request
    Auth->>Auth: Biometrie-Check + Signatur
    Auth->>User: Assertion (AuthenticatorData, Signature)

    User->>X2FA: POST /verify/complete (credential_id, assertion)
    X2FA->>DB: PublicKey und SignCount laden
    X2FA->>X2FA: verify_authentication_response() + SignCount-Prüfung
    X2FA->>DB: UPDATE sign_count
    X2FA->>X2FA: Return-JWT (verified: true, amr: ["face"])
    X2FA->>User: 302 Redirect → app/callback

    User->>App: Callback empfangen
    App->>App: Session erstellen
    App->>User: Dashboard
```

### 10.3 TOTP Setup (Fallback)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank
    participant Phone as Smartphone

    User->>App: 2FA einrichten (Legacy-Browser)
    App->>App: Erkennung: Kein WebAuthn
    App->>User: Redirect → 2fa.example.com/totp/setup?token=JWT

    User->>X2FA: GET /totp/setup?token=JWT
    X2FA->>X2FA: Base32-Secret generieren
    X2FA->>X2FA: Fernet-Verschlüsselung
    X2FA->>DB: INSERT totp_secrets (encrypted, verified=0)
    X2FA->>X2FA: QR-Code generieren (otpauth://)
    X2FA->>User: HTML (QR-Code + Secret-Text + Eingabefeld)

    User->>Phone: QR-Code scannen
    Phone->>User: 6-stelliger Code anzeigen

    User->>X2FA: POST /totp/setup/verify (code=123456)
    X2FA->>DB: Secret laden und entschlüsseln
    X2FA->>X2FA: pyotp.TOTP.verify() (Zeitfenster ±30s)
    X2FA->>DB: UPDATE verified=1
    X2FA->>User: Redirect zur App (success)
```

### 10.4 TOTP Verify (Login)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank
    participant Phone as Smartphone

    User->>App: Login
    App->>User: Redirect → 2fa.example.com/totp/verify?token=JWT

    User->>X2FA: GET /totp/verify?token=JWT
    X2FA->>DB: Prüfen ob totp_secret existiert
    X2FA->>User: HTML Eingabefeld (reines Formular)

    User->>Phone: Authenticator öffnen
    Phone->>User: Aktueller Code (z.B. 654321)

    User->>X2FA: POST /totp/verify (code=654321)
    X2FA->>DB: Secret laden + last_used_at prüfen
    X2FA->>X2FA: Validierung (Replay-Schutz)
    X2FA->>DB: UPDATE last_used_at=now()
    X2FA->>X2FA: Return-JWT (verified: true, amr: ["totp"])
    X2FA->>App: Redirect
```

### 10.5 Backup-Code Verify (Notfall)

```mermaid
sequenceDiagram
    participant User as User/Browser
    participant App as Haupt-App
    participant X2FA as X2FA-Service
    participant DB as Datenbank

    User->>App: Login (neues Gerät, kein FIDO2)
    App->>User: Redirect → 2fa.example.com/verify

    User->>X2FA: GET /verify
    X2FA->>User: Kein Schlüssel gefunden + Link Backup-Code verwenden

    User->>X2FA: GET /backup/verify?token=JWT
    X2FA->>User: Eingabefeld für 8-stelligen Code

    Note over User: Nutzer tippt A1B2C3D4 ein
    User->>X2FA: POST /backup/verify (code=A1B2C3D4)

    X2FA->>X2FA: Code hashen (bcrypt)
    X2FA->>DB: SELECT WHERE code_hash=HASH AND user_id=123 AND used_at IS NULL
    X2FA->>DB: UPDATE used_at=now()
    X2FA->>X2FA: Return-JWT (verified: true, amr: ["backup"], remaining: 9)

    X2FA->>User: Redirect zur App
    App->>User: Notfall-Login erfolgreich. Bitte neues 2FA einrichten.
```