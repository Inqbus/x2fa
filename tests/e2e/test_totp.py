"""E2E tests for TOTP setup and verification flows."""

import urllib.parse

import pyotp
import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# TOTP Setup
# ---------------------------------------------------------------------------


class TestTOTPSetup:
    def test_page_renders(self, page: Page, goto_with_session, live_server):
        """Setup page shows QR code, plaintext secret, and the code entry form."""
        goto_with_session("/totp/setup", setup_mode=True)

        expect(page.locator("img[alt='TOTP QR-Code']")).to_be_visible()
        expect(page.locator(".secret")).to_be_visible()
        expect(page.locator("#code")).to_be_visible()
        expect(page.locator("button[type='submit']")).to_be_visible()

    def test_wrong_code_shows_error(self, page: Page, goto_with_session, live_server):
        """A wrong confirmation code stays on the page and shows an error."""
        goto_with_session("/totp/setup", setup_mode=True)

        page.fill("#code", "000000")
        page.click("button[type='submit']")

        # Page reloads with error= query param → .error div becomes visible
        expect(page.locator(".error")).to_be_visible()
        expect(page.locator(".error")).not_to_be_empty()

    def test_correct_code_redirects_to_callback(
        self, page: Page, goto_with_session, capture_callback, live_server
    ):
        """A correct confirmation code completes setup and redirects to the RP callback."""
        goto_with_session("/totp/setup", setup_mode=True, user_id="e2e-totp-setup-ok")

        secret = page.locator(".secret").inner_text().strip()
        code = pyotp.TOTP(secret).now()

        page.fill("#code", code)
        url = capture_callback(lambda: page.click("button[type='submit']"))

        assert "code=" in url


# ---------------------------------------------------------------------------
# TOTP Verify
# ---------------------------------------------------------------------------


class TestTOTPVerify:
    def test_page_renders(
        self, page: Page, goto_with_session, create_totp, live_server
    ):
        """Verify page shows the code input and the backup-code link."""
        create_totp("e2e-totp-render")
        goto_with_session("/totp/verify", user_id="e2e-totp-render")

        expect(page.locator("#code")).to_be_visible()
        expect(page.locator("button[type='submit']")).to_be_visible()
        expect(page.locator("a[href='/backup/verify']")).to_be_visible()

    def test_wrong_code_shows_error(
        self, page: Page, goto_with_session, create_totp, live_server
    ):
        """A wrong code shows the error message without leaving the page."""
        create_totp("e2e-totp-wrong")
        goto_with_session("/totp/verify", user_id="e2e-totp-wrong")

        page.fill("#code", "000000")
        page.click("button[type='submit']")

        expect(page.locator(".error")).to_be_visible()

    def test_correct_code_redirects_to_callback(
        self, page: Page, goto_with_session, create_totp, capture_callback, live_server
    ):
        """A correct TOTP code completes verification and redirects to the RP callback."""
        secret = create_totp("e2e-totp-ok")
        goto_with_session("/totp/verify", user_id="e2e-totp-ok")

        code = pyotp.TOTP(secret).now()
        page.fill("#code", code)
        url = capture_callback(lambda: page.click("button[type='submit']"))

        assert "code=" in url

    def test_replay_rejected(
        self, page: Page, goto_with_session, create_totp, capture_callback, live_server
    ):
        """Using the same TOTP code a second time within the same window is rejected."""
        secret = create_totp("e2e-totp-replay")
        code = pyotp.TOTP(secret).now()

        # First use — must succeed
        goto_with_session("/totp/verify", user_id="e2e-totp-replay")
        page.fill("#code", code)
        capture_callback(lambda: page.click("button[type='submit']"))

        # Second use — same code, new session, must fail
        goto_with_session("/totp/verify", user_id="e2e-totp-replay")
        page.fill("#code", code)
        page.click("button[type='submit']")

        expect(page.locator(".error")).to_be_visible()
