"""Integrationstests für Backup-Code-Routen (/backup/verify)."""


def _create_backup_codes(client, user_id: str = "user_test", count: int = 10) -> list[str]:
    """Legt Backup-Codes in der DB an und gibt die Klartexte zurück."""
    from app.models import BackupCode, db
    from app.services.crypto import CryptoService

    with client.app_context():
        codes = CryptoService.generate_backup_codes(count)
        for code in codes:
            db.session.add(BackupCode(
                code_hash=CryptoService.hash_backup_code(code),
                user_id=user_id,
            ))
        db.session.commit()
    return codes


# ---------------------------------------------------------------------------
# GET /backup/verify
# ---------------------------------------------------------------------------

def test_backup_verify_get_no_session(client):
    status, _, _ = client.get("/backup/verify")
    assert status.startswith("400")


def test_backup_verify_get_valid(client):
    client.set_session()
    status, _, body = client.get("/backup/verify")
    assert status.startswith("200")
    assert b"Backup" in body


# ---------------------------------------------------------------------------
# POST /backup/verify
# ---------------------------------------------------------------------------

def test_backup_verify_no_session(client):
    status, _, _ = client.post_form("/backup/verify", {"code": "A1B2C3D4"})
    assert status.startswith("400")


def test_backup_verify_correct_code(client):
    codes = _create_backup_codes(client)
    client.set_session()
    status, headers, _ = client.post_form("/backup/verify", {"code": codes[0]})
    assert status.startswith("302")
    assert "/authorize" in headers.get("Location", "")
    assert "error" not in headers.get("Location", "")


def test_backup_verify_correct_code_lowercase(client):
    """Codes sollen case-insensitiv akzeptiert werden."""
    codes = _create_backup_codes(client)
    client.set_session()
    status, headers, _ = client.post_form("/backup/verify", {"code": codes[0].lower()})
    assert status.startswith("302")
    assert "error" not in headers.get("Location", "")


def test_backup_verify_wrong_code(client):
    _create_backup_codes(client)
    client.set_session()
    status, headers, _ = client.post_form("/backup/verify", {"code": "00000000"})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_backup_verify_already_used(client):
    """Einmal eingelöster Code darf nicht ein zweites Mal akzeptiert werden."""
    codes = _create_backup_codes(client)
    client.set_session()
    client.post_form("/backup/verify", {"code": codes[0]})
    client.set_session()
    status, headers, _ = client.post_form("/backup/verify", {"code": codes[0]})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_backup_verify_marks_code_as_used(client):
    """used_at wird nach Einlösung gesetzt."""
    from app.models import BackupCode
    from app.services.crypto import CryptoService

    codes = _create_backup_codes(client)
    client.set_session()
    client.post_form("/backup/verify", {"code": codes[0]})

    with client.app_context():
        used = [
            r for r in BackupCode.query.filter_by(user_id="user_test").all()
            if r.used_at is not None
        ]
    assert len(used) == 1


def test_backup_verify_rate_limit(client):
    """Nach 3 fehlgeschlagenen Versuchen wird die IP geblockt."""
    _create_backup_codes(client)
    for _ in range(3):
        client.set_session()
        client.post_form("/backup/verify", {"code": "00000000"})
    # 4. Versuch → Rate-Limit
    client.set_session()
    status, headers, _ = client.post_form("/backup/verify", {"code": "00000000"})
    assert status.startswith("302")
    assert "warten" in headers.get("Location", "")
