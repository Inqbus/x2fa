"""E2E tests for error handling and unauthenticated access."""

from playwright.sync_api import Page, expect


class TestUnauthenticated:
    def test_totp_verify_without_session_shows_error(self, page: Page, live_server: str):
        """Navigating to /totp/verify without an OIDC session returns a 400 error page."""
        response = page.goto(f"{live_server}/totp/verify")

        assert response.status == 400
        expect(page.locator("body")).to_contain_text("400")

    def test_totp_setup_without_session_shows_error(self, page: Page, live_server: str):
        """Navigating to /totp/setup without an OIDC session returns a 400 error page."""
        response = page.goto(f"{live_server}/totp/setup")

        assert response.status == 400

    def test_backup_verify_without_session_shows_error(self, page: Page, live_server: str):
        """Navigating to /backup/verify without an OIDC session returns a 400 error page."""
        response = page.goto(f"{live_server}/backup/verify")

        assert response.status == 400

    def test_setup_choose_without_session_shows_error(self, page: Page, live_server: str):
        """Navigating to /setup without an OIDC session returns a 400 error page."""
        response = page.goto(f"{live_server}/setup")

        assert response.status == 400


class TestNotFound:
    def test_unknown_route_returns_404(self, page: Page, live_server: str):
        """An unknown URL returns a 404 error page."""
        response = page.goto(f"{live_server}/this-does-not-exist")

        assert response.status == 404
        expect(page.locator("body")).to_contain_text("404")
