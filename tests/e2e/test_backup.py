"""E2E tests for backup code verification."""

import urllib.parse

import pytest
from playwright.sync_api import Page, expect


class TestBackupVerify:
    def test_page_renders(self, page: Page, goto_with_session, x2fa_server):
        """Backup verify page shows the code input and the warning box."""
        goto_with_session("/backup/verify")

        expect(page.locator("#code")).to_be_visible()
        expect(page.locator("button[type='submit']")).to_be_visible()
        expect(page.locator(".warn")).to_be_visible()

    def test_wrong_code_shows_error(
        self, page: Page, goto_with_session, create_backup_codes, x2fa_server
    ):
        """An invalid backup code shows the error message."""
        create_backup_codes("e2e-backup-wrong")
        goto_with_session("/backup/verify", user_id="e2e-backup-wrong")

        page.fill("#code", "DEADBEEF")
        page.click("button[type='submit']")

        expect(page.locator(".error")).to_be_visible()

    def test_correct_code_redirects_to_callback(
        self,
        page: Page,
        goto_with_session,
        create_backup_codes,
        capture_callback,
        x2fa_server,
    ):
        """A valid backup code completes verification and redirects to the RP callback."""
        codes = create_backup_codes("e2e-backup-ok")
        goto_with_session("/backup/verify", user_id="e2e-backup-ok")

        page.fill("#code", codes[0])
        url = capture_callback(lambda: page.click("button[type='submit']"))

        assert "code=" in url

    def test_used_code_is_rejected(
        self,
        page: Page,
        goto_with_session,
        create_backup_codes,
        capture_callback,
        x2fa_server,
    ):
        """A backup code that has already been used is rejected on a second attempt."""
        codes = create_backup_codes("e2e-backup-used")
        code = codes[0]

        # First use — must succeed and redirect to callback
        goto_with_session("/backup/verify", user_id="e2e-backup-used")
        page.fill("#code", code)
        capture_callback(lambda: page.click("button[type='submit']"))

        # Second use — same code must be rejected
        goto_with_session("/backup/verify", user_id="e2e-backup-used")
        page.fill("#code", code)
        page.click("button[type='submit']")

        expect(page.locator(".error")).to_be_visible()
