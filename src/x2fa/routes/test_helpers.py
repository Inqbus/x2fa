"""Test-only blueprint for E2E Playwright tests.

Registered only when config_name is 'testing' or 'e2e'. Never loaded in
production. Provides endpoints for injecting Flask session state and
creating DB fixtures that the Playwright browser needs.
"""

import base64
import json
import urllib.parse

from flask import Blueprint, redirect, request, session

test_bp = Blueprint("test_helpers", __name__, url_prefix="/test")


@test_bp.get("/session")
def set_session():
    """Set Flask session from base64url-encoded JSON, then redirect.

    Query params:
        d    – base64url-encoded JSON dict (session keys/values to set)
        next – URL to redirect to after setting the session (default: /)
    """
    data_b64 = request.args.get("d", "")
    next_url  = request.args.get("next", "/")

    # Padding-tolerant decode
    data = json.loads(base64.urlsafe_b64decode(data_b64 + "=="))
    session.clear()
    session.update(data)
    return redirect(next_url)
