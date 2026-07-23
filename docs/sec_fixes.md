# Security & Bug Audit — X2FA

**Datum:** 2026-07-23  
**Scope:** `src/x2fa/` — Python 3.11+, Flask, SQLAlchemy 2.0, bcrypt, py_webauthn

---

## CRITICAL

### [10] Unimportiertes globales `app` in `webauthn_helpers.py`

- **Datei:** `src/x2fa/helpers/webauthn_helpers.py:31,32,63,64,137,180,181`
- **Schwere:** CRITICAL
- **Problem:** `app` wird in `webauthn_helpers.py` **niemals importiert**. Es existiert nur als globales Modul-Level-Objekt in `wsgi.py:6` (`app = create_app()`). Die Helpers greifen implizit auf dieses globale `app` zu (`app.configure.x2fa.DOMAIN`). Wenn die Helpers vor dem App-Factory-Aufruf importiert werden (z.B. in CLI-Modus über `wsgi_cli.py`), gibt es einen `NameError`. Auch im Multi-Worker-Betrieb (gunicorn) ist der Zugriff auf ein globales Flask-App-Objekt aus einem shared-imported helper unsicher.
- **Betroffene Zeilen:** 31, 32, 63, 64, 137, 180, 181

```python
# Bisher (kaputt):
rp_id=app.configure.x2fa.DOMAIN,
rp_name=app.configure.x2fa.NAME,
```

- **Fix:** `current_app` aus Flask verwenden:

```python
from flask import current_app

def build_registration_options_json(user_id: str, challenge: bytes) -> str:
    options = generate_registration_options(
        rp_id=current_app.config.x2fa.DOMAIN,
        rp_name=current_app.config.x2fa.NAME,
        user_id=user_id.encode(),
        user_name=user_id,
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return options_to_json(options)
```

Analog für `verify_registration()` (Zeile 63-64), `build_authentication_options_json()` (Zeile 137) und `verify_authentication()` (Zeile 180-181).

---

## WARNING

### [1] Module-level mutable dict `CONFIGS`

- **Datei:** `src/x2fa/init_app/config.py:8`
- **Schwere:** WARNING
- **Problem:** `CONFIGS` ist ein module-level dict. Es wird nur gelesen, nicht geschrieben, also **funktionell sicher**. Aber es ist ein mutables dict-Literal auf Modulebene — theoretisch könnte jeder Code `CONFIGS["x2fa"] = "evil.toml"` ausführen.
- **Code:**

```python
CONFIGS = {
    "x2fa": "x2fa_config.toml",
    "x2fa_babel": "babel_config.toml",
    "x2fa_database": "db_config.toml",
    "x2fa_ratelimit": "ratelimit_config.toml",
    "x2fa_security": "security_config.toml",
}
```

- **Fix:** Als `Final` typisieren:

```python
from typing import Final

CONFIGS: Final[dict[str, str]] = {
    "x2fa": "x2fa_config.toml",
    "x2fa_babel": "babel_config.toml",
    "x2fa_database": "db_config.toml",
    "x2fa_ratelimit": "ratelimit_config.toml",
    "x2fa_security": "security_config.toml",
}
```

---

### [24] Naive Datetimes in Sentinel-Konstanten

- **Datei:** `src/x2fa/constants.py:13-16`
- **Schwere:** WARNING
- **Problem:** Die Sentinel-Datetimes `NEVER_USED` und `NEVER_EXPIRES` sind **timezone-naiv**. Der Code behandelt dies bewusst (Kommentar in constants.py:5-8), aber es bedeutet, dass alle DB-Vergleiche naive Datetimes verwenden. Wenn jemals `timezone=True` bei den DateTime-Columns gesetzt wird, brechen alle Vergleiche. Die Konstanten werden in `totp_helpers.py:59` und `model/oidc.py:92-93` mit `.replace(tzinfo=timezone.utc)` "gefixt", was ein Workaround ist.
- **Code:**

```python
NEVER_USED    = datetime(1970, 1, 1)
NEVER_EXPIRES = datetime(9999, 12, 31, 23, 59, 59)
```

- **Fix:**

```python
from datetime import datetime, timezone

NEVER_USED    = datetime(1970, 1, 1, tzinfo=timezone.utc)
NEVER_EXPIRES = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
```

Und alle DateTime-Columns in den SQLAlchemy-Modellen mit `timezone=True` definieren (z.B. `DateTime(timezone=True)`).

---

### [29] Path Traversal in `cli.py` — unsichere Client-ID-Sanitization

- **Datei:** `src/x2fa/cli.py:495-498`
- **Schwere:** WARNING
- **Problem:** `client_id` kommt vom CLI-Argument und wird nur durch `.replace("/", "_").replace(":", "_")` "gesichert". Ein Client-ID wie `../../../etc` würde zu `____../../../etc` werden (nur Slash-Ersatz, `..` bleibt). `os.path.join` mit einem absoluten Pfad als zweiten Argument ignoriert das erste Argument komplett.
- **Code:**

```python
    safe_id = client_id.replace("/", "_").replace(":", "_")
    key_path  = os.path.join(output, f"{safe_id}.key.pem")
    cert_path = os.path.join(output, f"{safe_id}.cert.pem")
```

- **Fix:**

```python
    import re
    safe_id = re.sub(r'[^a-zA-Z0-9._-]', '', client_id)
    key_path = Path(output) / f"{safe_id}.key.pem"
    cert_path = Path(output) / f"{safe_id}.cert.pem"
```

---

## INFO

### [5] Toter Code: `threading.local()` in `Database.__init__`

- **Datei:** `src/x2fa/init_app/database.py:20`
- **Schwere:** INFO
- **Problem:** `self._local = threading.local()` wird initialisiert, aber **niemals verwendet**. Der Code nutzt stattdessen Flask's `g`-Objekt (Zeile 48: `g.db_session = self._Session()`). Der `threading.local()` ist toter Code und verwirrend.
- **Code:**

```python
    def __init__(self):
        self.engine = None
        self._Session = None
        self._local = threading.local()  # <-- wird nie verwendet
        self.is_configured = False
```

- **Fix:** Zeile 20 entfernen.

---

### [11] `session.commit()` ohne `session.refresh()` — stale Instances (potenziell)

- **Datei:** `src/x2fa/routes/setup.py:126`, `src/x2fa/routes/verify.py:137`
- **Schwere:** INFO
- **Problem:** Nach `commit()` wird das modifizierte Objekt direkt weiterverwendet. In der **gleichen Session** ist das OK (dirty tracking), aber es ist ein Wartungsrisiko — wer später ein Objekt aus einer **anderen** Session liest, bekommt stale Daten.
- **Code (setup.py:125-127):**

```python
    ch.used = True
    g.db_session.commit()
    challenge_bytes = bytes(ch.challenge)  # ch.challenge wird gelesen
```

- **Fazit:** In diesem Codebase **funktionell kein Bug** (alle Zugriffe sind in derselben Session), aber ein Wartungsrisiko.
- **Fix:** Bei Bedarf `session.refresh(obj)` nach `commit()` vor dem Lesen.

---

## CLEAN (keine Bugs gefunden)

| Kategorie | Beschreibung | Status |
|---|---|---|
| [1] Module-level mutable globals | Keine Listen/Dicts/Sets ohne Lock | ✅ CLEAN |
| [2] Pydantic model mutation | N/A — kein Pydantic im Codebase | ✅ N/A |
| [3] BackgroundTasks | N/A — Flask, nicht FastAPI | ✅ N/A |
| [4] Depends() | N/A — Flask, nicht FastAPI | ✅ N/A |
| [6] Mutable default args | Keine `def foo(x=[])` gefunden | ✅ CLEAN |
| [7] Mutable class attributes | Keine Klassen mit mutable Defaults | ✅ CLEAN |
| [8] Request body mutation | `request.get_json()` erstellt neue Dicts | ✅ CLEAN |
| [9] Mutable caches | Kein `lru_cache`/`functools.cache` | ✅ CLEAN |
| [12] Lazy Loading | Keine SQLAlchemy Relationships definiert | ✅ CLEAN |
| [13] Missing `.scalars()` | Alle `session.execute()` verwenden `.scalars()` | ✅ CLEAN |
| [14] autoflush/flush | autoflush aktiv (SQLAlchemy Standard) | ✅ CLEAN |
| [15] session.close() | `teardown_appcontext` schließt garantiert | ✅ CLEAN |
| [16] response_model | N/A — Flask, nicht FastAPI | ✅ N/A |
| [17] Field(default=...) | N/A — kein Pydantic | ✅ N/A |
| [18] Union statt `\|` | Kein `Union[X, Y]` gefunden | ✅ CLEAN |
| [19] Optional statt `\|None` | Kein `Optional[X]` gefunden | ✅ CLEAN |
| [20] @validator | Kein Pydantic — kein `@validator` | ✅ N/A |
| [21] Bare `except:` | Alle excepts fangen spezifische Exceptions | ✅ CLEAN |
| [22] open() ohne with | Alle `open()` verwenden `with` | ✅ CLEAN |
| [23] json.loads ohne try/except | Alle `json.loads` sind gewrappt | ✅ CLEAN |
| [25] `== None` | Alle None-Vergleiche nutzen `is None` | ✅ CLEAN |
| [26] hashlib.md5 | SHA-256 verwendet, kein MD5 | ✅ CLEAN |
| [27] random statt secrets | `secrets.token_hex()` korrekt verwendet | ✅ CLEAN |
| [28] eval/exec | Kein `eval()`/`exec()` gefunden | ✅ CLEAN |
| [30] SQL Injection | SQLAlchemy ORM, keine Raw SQL mit f-Strings | ✅ CLEAN |