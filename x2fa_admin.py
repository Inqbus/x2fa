#!/usr/bin/env python3
"""X2FA Admin CLI – direkter Datenbankzugriff für Administratoren."""

import argparse
import os
import sys
from datetime import datetime, timezone


def _bootstrap() -> None:
    """Lädt .env, initialisiert Crypto und DB."""
    # .env einlesen
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

    secret = os.environ.get("X2FA_SECRET", "")
    if not secret or len(secret) < 32:
        print("FEHLER: X2FA_SECRET fehlt oder zu kurz.", file=sys.stderr)
        sys.exit(1)

    from crypto import init_crypto
    from models import init_db
    init_crypto(secret)
    init_db()


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------

def cmd_list_credentials(args) -> None:
    from repositories import CredentialRepo
    creds = CredentialRepo.list_by_user(args.user_id)
    if not creds:
        print(f"Keine Credentials für '{args.user_id}'.")
        return
    print(f"{'credential_id (hex)':<48} {'typ':<10} {'passkey':<8} {'sign_count':<12} {'zuletzt'}")
    print("-" * 100)
    for c in creds:
        last = c.last_used_at.strftime("%Y-%m-%d %H:%M") if c.last_used_at else "—"
        print(f"{bytes(c.credential_id).hex():<48} {c.authenticator_type:<10} {str(c.is_passkey):<8} {c.sign_count:<12} {last}")


def cmd_revoke_credential(args) -> None:
    from repositories import CredentialRepo
    cred_id = bytes.fromhex(args.credential_id)
    cred = CredentialRepo.get_by_id(cred_id)
    if cred is None:
        print(f"Credential '{args.credential_id}' nicht gefunden.")
        sys.exit(1)
    CredentialRepo.delete(cred_id)
    print(f"Credential '{args.credential_id}' widerrufen.")


def cmd_reset_totp(args) -> None:
    from repositories import TOTPRepo
    rec = TOTPRepo.get(args.user_id)
    if rec is None:
        print(f"Kein TOTP-Secret für '{args.user_id}'.")
        return
    TOTPRepo.delete(args.user_id)
    print(f"TOTP-Secret für '{args.user_id}' gelöscht. Neues Setup erforderlich.")


def cmd_generate_backup(args) -> None:
    from crypto import generate_backup_codes, hash_backup_code
    from repositories import BackupRepo

    existing = BackupRepo.count_valid(args.user_id)
    if existing > 0 and not args.force:
        print(f"'{args.user_id}' hat noch {existing} gültige Backup-Codes.")
        print("Mit --force überschreiben (alle alten Codes werden gelöscht).")
        sys.exit(1)

    BackupRepo.delete_all(args.user_id)
    codes = generate_backup_codes(10)
    hashes = [hash_backup_code(c) for c in codes]
    BackupRepo.save_many(args.user_id, hashes)

    print(f"10 neue Backup-Codes für '{args.user_id}':")
    print()
    for i, code in enumerate(codes, 1):
        print(f"  {i:2d}. {code}")
    print()
    print("ACHTUNG: Codes jetzt sichern – sie werden nicht erneut angezeigt.")


def cmd_stats(args) -> None:
    from repositories import AuditRepo, BackupRepo, CredentialRepo
    from models import SessionLocal, Credential, TOTPSecret, BackupCode, AuditLog
    from sqlalchemy import func

    with SessionLocal() as db:
        n_creds   = db.query(func.count(Credential.credential_id)).scalar()
        n_totp    = db.query(func.count(TOTPSecret.user_id)).filter_by(verified=True).scalar()
        n_backup  = db.query(func.count(BackupCode.code_hash)).filter(BackupCode.used_at.is_(None)).scalar()
        n_audit   = db.query(func.count(AuditLog.id)).scalar()

    print("=== X2FA Statistiken ===")
    print(f"  Registrierte FIDO2-Credentials : {n_creds}")
    print(f"  Verifizierte TOTP-Secrets       : {n_totp}")
    print(f"  Verbleibende Backup-Codes        : {n_backup}")
    print(f"  Audit-Log-Einträge               : {n_audit}")
    print()

    stats = AuditRepo.stats()
    if stats:
        print("=== Audit-Ereignisse ===")
        for key, count in sorted(stats.items()):
            print(f"  {key:<40} {count}")


def cmd_audit(args) -> None:
    from repositories import AuditRepo
    entries = AuditRepo.list_by_user(args.user_id, limit=args.limit)
    if not entries:
        print(f"Keine Audit-Einträge für '{args.user_id}'.")
        return
    print(f"{'Zeitpunkt':<20} {'Action':<10} {'Method':<22} {'ip_hash[:12]'}")
    print("-" * 80)
    for e in entries:
        ts = e.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print(f"{ts:<20} {e.action:<10} {e.method:<22} {e.ip_hash[:12]}…")


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

def main() -> None:
    _bootstrap()

    parser = argparse.ArgumentParser(
        prog="x2fa_admin",
        description="X2FA Admin CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list-credentials
    p = sub.add_parser("list-credentials", help="FIDO2-Credentials eines Users auflisten")
    p.add_argument("user_id")
    p.set_defaults(func=cmd_list_credentials)

    # revoke-credential
    p = sub.add_parser("revoke-credential", help="FIDO2-Credential widerrufen")
    p.add_argument("credential_id", help="Credential-ID als Hex-String")
    p.set_defaults(func=cmd_revoke_credential)

    # reset-totp
    p = sub.add_parser("reset-totp", help="TOTP-Secret eines Users löschen")
    p.add_argument("user_id")
    p.set_defaults(func=cmd_reset_totp)

    # generate-backup
    p = sub.add_parser("generate-backup", help="Neue Backup-Codes generieren")
    p.add_argument("user_id")
    p.add_argument("--force", action="store_true", help="Bestehende Codes überschreiben")
    p.set_defaults(func=cmd_generate_backup)

    # stats
    p = sub.add_parser("stats", help="Systemstatistiken anzeigen")
    p.set_defaults(func=cmd_stats)

    # audit
    p = sub.add_parser("audit", help="Audit-Log eines Users anzeigen")
    p.add_argument("user_id")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_audit)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
