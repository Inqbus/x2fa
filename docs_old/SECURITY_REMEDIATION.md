# Security Remediation Proposal

## 1. Remove Demo Endpoints from Production

**Severity:** CRITICAL  
**Location:** `src/x2fa/routes/auth.py:237`

### Problem
Der `/done`-Endpoint ist ein Debug/Demo-Endpunkt, der `client_secret` im Klartext
ausgibt. In einer Produktionsumgebung stellt dies ein schwerwiegendes Sicherheitsrisiko
dar.

### Fix
- Endpoint vollständig entfernen oder nur bei `app.debug == True` registrieren
- Alle Demo/Debug-Endpoints in einer separaten `debug.py` auslagern, die nicht in
  der Produktions-WSGI geladen wird

```python
# src/x2fa/routes/auth.py
# ENTFERNEN:
@app.route("/done")
def demo_done():
    return jsonify({"client_secret": ...})
```

---

## 2. SSL Verification for JWKS Fetch

**Severity:** CRITICAL  
**Location:** `src/x2fa/oidc/grants.py:222`

### Problem
`requests.get()` wird ohne SSL-Verifikation aufgerufen. Ein Angreifer kann einen
Man-in-the-Middle-Angriff durchführen und ein gefälschtes JWKS zurückliefern, um
ID-Tokens zu fälschen.

### Fix
SSL-Verifikation erzwingen und Zertifikats-Pinning für bekannte Endpunkte in Betracht ziehen.

```python
# Vorher:
resp = requests.get(jwks_uri)

# Nachher:
resp = requests.get(jwks_uri, verify=True, timeout=10)
resp.raise_for_status()
```

---

## 3. Client Secret Handling

**Severity:** HIGH

### Problem
`client_secret` wird an mehreren Stellen im Klartext verarbeitet und könnte in Logs
oder Fehlermeldungen landen.

### Fix
- `client_secret` niemals in Logs schreiben
- Secret-Hashing für Vergleich verwenden (bereits teilweise implementiert via
  `hmac.compare_digest`)
- Secret nur bei Bedarf im Response zurückgeben, nie in Audit-Logs

---

## 4. Path Traversal Protection

**Severity:** HIGH  
**Location:** `installer/ca.py`, `installer/config_writer.py`

### Problem
CA-Zertifikatspfade und andere Dateipfade werden nicht auf Path-Traversal-Angriffe
geprüft. Ein Angreifer könnte über manipulierte Konfiguration Dateien an beliebigen
Positionen schreiben.

### Fix
Pfadvalidierung mit `pathlib.resolve()` und Prüfung, dass der Pfad innerhalb des
erwarteten Verzeichnisses liegt.

```python
from pathlib import Path

def _safe_path(base: Path, filename: str) -> Path:
    """Resolve and validate path stays within base directory."""
    p = (base / filename).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise ValueError(f"Path traversal detected: {filename}")
    return p
```

---

## 5. Race Condition in ExecuteScreen

**Severity:** MEDIUM  
**Location:** `installer/screens/execute.py:249`

### Problem
`cfg.generated_files` wird aus einem Hintergrundthread (`@work(thread=True)`)
modifiziert, ohne Synchronisation. Dies kann zu Datenkorruption führen.

### Fix
`call_from_thread` verwenden oder ein `threading.Lock` für shared state.

```python
# Vorher:
cfg.generated_files += list(cert_paths.values())

# Nachher:
self.app.call_from_thread(self._update_generated_files, list(cert_paths.values()))

def _update_generated_files(self, paths_list: list) -> None:
    self.app.config.generated_files.extend(paths_list)
```

---

## 6. Subprocess Timeout

**Severity:** MEDIUM  
**Location:** `installer/runner.py`

### Problem
`subprocess.run()` für Flask-Befehle hat kein explizites Timeout. Ein hängender
Flask-Prozess blockiert den Installer indefinitely.

### Fix
Timeout hinzufügen und `TimeoutExpired` abfangen.

```python
result = subprocess.run(
    [sys.executable, "-m", "flask"] + args,
    cwd=paths.config_dir(),
    env=env,
    capture_output=True,
    text=True,
    timeout=60,  # 60 Sekunden Timeout
)
```

---

## 7. TOCTOU Race in Permission Check

**Severity:** LOW  
**Location:** `installer/screens/welcome.py:61`

### Problem
`os.access()` prüft Berechtigungen vor dem eigentlichen Dateizugriff (TOCTOU).
Zwischen Prüfung und Nutzung kann sich der Dateizugriff ändern.

### Fix
Direkt versuchen zu schreiben und Fehler abfangen (EAFP statt LBYL).

```python
# Vorher:
if os.access(path, os.W_OK):
    return True, ""

# Nachher:
try:
    test_file = path / ".write_test"
    test_file.write_text("")
    test_file.unlink()
    return True, ""
except OSError:
    return False, f"chmod u+rwx {path}"
```

---

## Summary

| # | Issue | Severity | Effort |
|---|-------|----------|--------|
| 1 | Demo Endpoint | CRITICAL | 5 min |
| 2 | JWKS SSL Verification | CRITICAL | 10 min |
| 3 | Client Secret Handling | HIGH | 30 min |
| 4 | Path Traversal | HIGH | 20 min |
| 5 | Race Condition | MEDIUM | 15 min |
| 6 | Subprocess Timeout | MEDIUM | 10 min |
| 7 | TOCTOU Race | LOW | 10 min |

**Gesamtaufwand:** ~100 min