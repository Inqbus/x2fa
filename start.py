#!/usr/bin/env python3
"""X2FA Bootstrap — liest .env, validiert Konfiguration, startet den Service."""

import argparse
import os
import sys

# .env einlesen (vor allem anderen)
def load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

load_dotenv()

# ---------------------------------------------------------------------------
# Pflicht-Konfiguration validieren
# ---------------------------------------------------------------------------

def validate_config() -> dict:
    errors = []

    secret = os.environ.get("X2FA_SECRET", "")
    if not secret:
        errors.append(
            "X2FA_SECRET ist nicht gesetzt.\n"
            "  Generieren mit: openssl rand -hex 32"
        )
    elif len(secret) < 32:
        errors.append(
            f"X2FA_SECRET ist zu kurz ({len(secret)} Zeichen, mind. 32 erforderlich)."
        )

    domain = os.environ.get("X2FA_DOMAIN", "")
    if not domain:
        errors.append(
            "X2FA_DOMAIN ist nicht gesetzt (z.B. 2fa.example.com)."
        )

    if errors:
        print("FEHLER: X2FA kann nicht gestartet werden.\n")
        for err in errors:
            print(f"  • {err}")
        sys.exit(1)

    return {
        "secret": secret,
        "domain": domain,
        "database_url": os.environ.get("X2FA_DATABASE_URL", "sqlite:///x2fa.db"),
        "host": os.environ.get("X2FA_HOST", "127.0.0.1"),
        "port": int(os.environ.get("X2FA_PORT", "5000")),
    }


# ---------------------------------------------------------------------------
# Backend-Konfiguration
# ---------------------------------------------------------------------------

CADDY_TEMPLATE = """\
{domain} {{
    reverse_proxy 127.0.0.1:{port}
}}
"""

NGINX_TEMPLATE = """\
server {{
    listen 443 ssl;
    server_name {domain};

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }}
}}
"""

TRAEFIK_HINT = """\
# Füge folgende Labels zu deinem Docker-Service hinzu:
# traefik.enable=true
# traefik.http.routers.x2fa.rule=Host(`{domain}`)
# traefik.http.routers.x2fa.tls.certresolver=letsencrypt
"""


def configure_backend(backend: str, domain: str, port: int) -> None:
    if backend == "caddy":
        config = CADDY_TEMPLATE.format(domain=domain, port=port)
        path = "Caddyfile"
        with open(path, "w") as f:
            f.write(config)
        print(f"  Caddyfile geschrieben: {path}")
        print("  Starten mit: caddy run")

    elif backend == "nginx":
        config = NGINX_TEMPLATE.format(domain=domain, port=port)
        path = f"{domain}.nginx.conf"
        with open(path, "w") as f:
            f.write(config)
        print(f"  nginx-Konfiguration geschrieben: {path}")
        print(f"  Einbinden in /etc/nginx/sites-enabled/ und nginx reload")

    elif backend == "traefik":
        print(TRAEFIK_HINT.format(domain=domain))

    elif backend == "none":
        print(f"  Kein Reverse-Proxy konfiguriert.")
        print(f"  X2FA lauscht auf http://{domain}:{port}")


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="X2FA Microservice Bootstrap")
    parser.add_argument(
        "--backend",
        choices=["caddy", "nginx", "traefik", "none"],
        default="none",
        help="Reverse-Proxy konfigurieren",
    )
    args = parser.parse_args()

    print("X2FA startet...")

    config = validate_config()
    print(f"  Domain:   {config['domain']}")
    print(f"  Datenbank: {config['database_url']}")

    # Crypto initialisieren
    from crypto import init_crypto
    init_crypto(config["secret"])
    print("  Kryptographie: OK")

    # Audit-Salt initialisieren
    from audit import init_audit
    init_audit(config["secret"])
    print("  Audit-Logging: OK")

    # Datenbank initialisieren
    from models import init_db
    init_db()
    print("  Datenbank: OK")

    # WebAuthn initialisieren
    from webauthn_helpers import init_webauthn
    import os
    os.environ["X2FA_DOMAIN"] = config["domain"]
    init_webauthn(config["domain"])
    print("  WebAuthn: OK")

    # Reverse-Proxy konfigurieren
    configure_backend(args.backend, config["domain"], config["port"])

    # Bottle-App starten
    from x2fa import app
    print(f"\nX2FA läuft auf http://{config['host']}:{config['port']}")
    app.run(host=config["host"], port=config["port"], quiet=True)


if __name__ == "__main__":
    main()
