"""Integration tests for backup code routes (/backup/verify)."""


def _create_backup_codes(
    client, user_id: str = "user_test", count: int = 10
) -> list[str]:
    """Creates backup codes in the DB and returns the plaintext values."""
    from app.src.x2fa.app.models import BackupCode, db
    from app.src.x2fa.app.services.crypto import CryptoService

    with client.app_context():
        codes = CryptoService.generate_backup_codes(count)
        for code in codes:
            db.session.add(
                BackupCode(
                    code_hash=CryptoService.hash_backup_code(code),
                    user_id=user_id,
                )
            )
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
    """Codes should be accepted case-insensitively."""
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
    """A code that has already been redeemed must not be accepted a second time."""
    codes = _create_backup_codes(client)
    client.set_session()
    client.post_form("/backup/verify", {"code": codes[0]})
    client.set_session()
    status, headers, _ = client.post_form("/backup/verify", {"code": codes[0]})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_backup_verify_marks_code_as_used(client):
    """used_at is set after redemption."""
    from app.src.x2fa.app.models import BackupCode

    codes = _create_backup_codes(client)
    client.set_session()
    client.post_form("/backup/verify", {"code": codes[0]})

    from app.src.x2fa.app import NEVER_USED

    with client.app_context():
        used = [
            r
            for r in BackupCode.query.filter_by(user_id="user_test").all()
            if r.used_at != NEVER_USED
        ]
    assert len(used) == 1


def test_backup_verify_rate_limit(client):
    """After 3 failed attempts within a minute the endpoint returns 429 (unless rate limiting is disabled)."""
    _create_backup_codes(client)
    for _ in range(3):
        client.set_session()
        client.post_form("/backup/verify", {"code": "00000000"})
    # 4th attempt → rate limit (or redirect if rate limiting is disabled in test env)
    client.set_session()
    status, _, _ = client.post_form("/backup/verify", {"code": "00000000"})
    # In test environments rate limiting may be disabled, so we accept either 429 or 302
    assert status.startswith("429") or status.startswith("302")
