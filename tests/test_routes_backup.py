"""Integrationstests für Backup-Code-Routen."""


def _create_backup_codes(user_id="user_test", count=10) -> list[str]:
    from crypto import generate_backup_codes, hash_backup_code
    from repositories import BackupRepo
    codes = generate_backup_codes(count)
    BackupRepo.save_many(user_id, [hash_backup_code(c) for c in codes])
    return codes


# ---------------------------------------------------------------------------
# GET /backup/verify
# ---------------------------------------------------------------------------

def test_backup_verify_get_valid(client, verify_token):
    status, _, body = client.get("/backup/verify", query=f"token={verify_token}")
    assert status.startswith("200")
    assert b"Backup-Code" in body


def test_backup_verify_get_no_token(client):
    status, _, _ = client.get("/backup/verify")
    assert status.startswith("400")


# ---------------------------------------------------------------------------
# POST /backup/verify
# ---------------------------------------------------------------------------

def test_backup_verify_correct_code(client, verify_token):
    codes = _create_backup_codes()

    status, headers, _ = client.post_form("/backup/verify", {"token": verify_token, "code": codes[0]})
    assert status.startswith("302")
    loc = headers.get("Location", "")
    assert "https://app/cb" in loc
    assert "error" not in loc


def test_backup_verify_correct_code_lowercase(client, verify_token):
    """Codes sollen case-insensitiv akzeptiert werden."""
    codes = _create_backup_codes()
    status, headers, _ = client.post_form("/backup/verify", {"token": verify_token, "code": codes[0].lower()})
    assert status.startswith("302")
    assert "error" not in headers.get("Location", "")


def test_backup_verify_wrong_code(client, verify_token):
    _create_backup_codes()
    status, headers, _ = client.post_form("/backup/verify", {"token": verify_token, "code": "00000000"})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_backup_verify_already_used(client, verify_token):
    codes = _create_backup_codes()
    client.post_form("/backup/verify", {"token": verify_token, "code": codes[0]})
    # Zweiter Versuch mit demselben Code
    status, headers, _ = client.post_form("/backup/verify", {"token": verify_token, "code": codes[0]})
    assert status.startswith("302")
    assert "error" in headers.get("Location", "")


def test_backup_verify_decrements_remaining(client, verify_token):
    from crypto import verify_jwt
    codes = _create_backup_codes()

    _, headers, _ = client.post_form("/backup/verify", {"token": verify_token, "code": codes[0]})
    loc = headers.get("Location", "")
    return_token = loc.split("token=")[1]
    payload = verify_jwt(return_token)
    assert payload["remaining_codes"] == 9
    assert payload["amr"] == ["backup"]


def test_backup_verify_rate_limit(client, verify_token):
    _create_backup_codes()
    # 5 fehlgeschlagene Versuche
    for _ in range(5):
        client.post_form("/backup/verify", {"token": verify_token, "code": "00000000"})
    # 6. Versuch → Rate-Limit
    status, headers, _ = client.post_form("/backup/verify", {"token": verify_token, "code": "00000000"})
    assert status.startswith("302")
    assert "warten" in headers.get("Location", "")


def test_backup_verify_rate_limit_does_not_block_correct_after_reset(client, verify_token):
    """Rate-Limiter gilt pro User — nach Reset (neuer Test) wieder offen."""
    codes = _create_backup_codes()
    # Frischer State durch clean_db + _backup_attempts.clear() in Fixture
    status, headers, _ = client.post_form("/backup/verify", {"token": verify_token, "code": codes[0]})
    assert status.startswith("302")
    assert "error" not in headers.get("Location", "")


def test_backup_verify_invalid_token(client):
    status, _, _ = client.post_form("/backup/verify", {"token": "BAD", "code": "A1B2C3D4"})
    assert status.startswith("400")
