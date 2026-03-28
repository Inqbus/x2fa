"""Dünner Wrapper um py_webauthn 2.x für X2FA."""

import os

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    RegistrationCredential,
    AuthenticationCredential,
)

_DOMAIN: str | None = None


def init_webauthn(domain: str) -> None:
    global _DOMAIN
    _DOMAIN = domain


def _require_domain() -> str:
    if not _DOMAIN:
        raise RuntimeError("webauthn_helpers.init_webauthn() wurde nicht aufgerufen.")
    return _DOMAIN


# ---------------------------------------------------------------------------
# Registrierung
# ---------------------------------------------------------------------------

def build_registration_options_json(user_id: str, challenge: bytes) -> str:
    """Gibt JSON-String zurück, der direkt an das Frontend gesendet werden kann."""
    domain = _require_domain()
    options = generate_registration_options(
        rp_id=domain,
        rp_name="X2FA",
        user_id=user_id.encode(),
        user_name=user_id,
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return options_to_json(options)


def verify_registration(challenge: bytes, credential_json: str) -> dict:
    """Verifiziert die Registrierungsantwort des Browsers.

    Gibt zurück:
        {
            credential_id: bytes,
            public_key: bytes,
            sign_count: int,
            is_passkey: bool,
        }
    Wirft ValueError bei Fehler.
    """
    domain = _require_domain()
    try:
        credential = RegistrationCredential.parse_raw(credential_json)
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=domain,
            expected_origin=f"https://{domain}",
            require_user_verification=True,
        )
    except Exception as exc:
        raise ValueError(f"Registrierung fehlgeschlagen: {exc}") from exc

    is_passkey = (
        verification.credential_backed_up is True
        if hasattr(verification, "credential_backed_up")
        else False
    )

    return {
        "credential_id": verification.credential_id,
        "public_key": verification.credential_public_key,
        "sign_count": verification.sign_count,
        "is_passkey": is_passkey,
    }


# ---------------------------------------------------------------------------
# Authentifizierung
# ---------------------------------------------------------------------------

def build_authentication_options_json(
    challenge: bytes, credential_ids: list[bytes]
) -> str:
    domain = _require_domain()
    allow_credentials = [
        PublicKeyCredentialDescriptor(id=cred_id)
        for cred_id in credential_ids
    ]
    options = generate_authentication_options(
        rp_id=domain,
        challenge=challenge,
        allow_credentials=allow_credentials,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return options_to_json(options)


def verify_authentication(
    challenge: bytes,
    credential_json: str,
    stored_public_key: bytes,
    stored_sign_count: int,
) -> int:
    """Verifiziert die Authentifizierungsantwort.

    Gibt den neuen sign_count zurück.
    Wirft ValueError bei Fehler oder Clone-Verdacht (sign count regression).
    """
    domain = _require_domain()
    try:
        credential = AuthenticationCredential.parse_raw(credential_json)
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=domain,
            expected_origin=f"https://{domain}",
            credential_public_key=stored_public_key,
            credential_current_sign_count=stored_sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        raise ValueError(f"Authentifizierung fehlgeschlagen: {exc}") from exc

    new_count = verification.new_sign_count
    # Strikte Prüfung: Replay / Clone-Schutz
    if stored_sign_count > 0 and new_count <= stored_sign_count:
        raise ValueError(
            f"Sign-Count-Regression: gespeichert={stored_sign_count}, "
            f"neu={new_count}. Möglicher Authenticator-Klon."
        )

    return new_count
