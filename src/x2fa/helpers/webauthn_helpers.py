"""Thin wrapper around py_webauthn 2.x for X2FA."""

# import os

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from x2fa.config import cfg


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def build_registration_options_json(user_id: str, challenge: bytes) -> str:
    """Returns a JSON string that can be sent directly to the frontend."""
    options = generate_registration_options(
        rp_id=cfg.x2fa.DOMAIN,
        rp_name=cfg.x2fa.NAME,
        user_id=user_id.encode(),
        user_name=user_id,
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # No authenticator_attachment → browser accepts platform (TouchID/Hello)
            # AND roaming authenticators (YubiKey, Nitrokey, HSM)
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return options_to_json(options)


def verify_registration(challenge: bytes, credential_json: str) -> dict:
    """Verifies the browser's registration response.

    Returns:
        {
            credential_id: bytes,
            public_key: bytes,
            sign_count: int,
            is_passkey: bool,
        }
    Raises ValueError on failure.
    """

    try:
        verification = verify_registration_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_rp_id=cfg.x2fa.DOMAIN,
            expected_origin=cfg.x2fa.ORIGIN,
            require_user_verification=True,
        )
    except Exception as exc:
        raise ValueError(f"Registration failed: {exc}") from exc

    is_passkey = (
        verification.credential_backed_up is True
        if hasattr(verification, "credential_backed_up")
        else False
    )

    # device_type: single_device / multi_device (from py_webauthn 2.x)
    device_type = "single_device"
    if hasattr(verification, "credential_device_type"):
        try:
            from webauthn.helpers.structs import CredentialDeviceType
            if verification.credential_device_type == CredentialDeviceType.MULTI_DEVICE:
                device_type = "multi_device"
        except Exception:
            pass

    # Authenticator type: platform (biometrics/TPM) vs. roaming (USB/NFC/BLE)
    # Passkeys and multi-device credentials are typically platform authenticators.
    authenticator_type = "roaming"
    if is_passkey or device_type == "multi_device":
        authenticator_type = "platform"
    elif hasattr(verification, "authenticator_data"):
        # Fallback: empty AAGUID → usually platform-internal
        aaguid = getattr(verification, "aaguid", None)
        if aaguid and str(aaguid) == "00000000-0000-0000-0000-000000000000":
            authenticator_type = "platform"

    # Transport from the JSON payload (provided by the browser via getTransports())
    import json as _json
    transport: str | None = None
    try:
        _data = _json.loads(credential_json)
        transports = _data.get("transports") or _data.get("response", {}).get("transports")
        if transports:
            transport = ",".join(transports) if isinstance(transports, list) else str(transports)
    except Exception:
        pass

    return {
        "credential_id": verification.credential_id,
        "public_key": verification.credential_public_key,
        "sign_count": verification.sign_count,
        "is_passkey": is_passkey,
        "authenticator_type": authenticator_type,
        "device_type": device_type,
        "transport": transport,
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def build_authentication_options_json(
    challenge: bytes, credential_ids: list[bytes], transports: list[list[str]] | None = None
) -> str:
    domain = _require_domain()
    def _to_transport_enums(raw: list[str] | None) -> list[AuthenticatorTransport] | None:
        if not raw:
            return None
        result = []
        for t in raw:
            try:
                result.append(AuthenticatorTransport(t))
            except ValueError:
                pass
        return result or None

    allow_credentials = [
        PublicKeyCredentialDescriptor(
            id=cred_id,
            transports=_to_transport_enums(
                transports[i] if transports and i < len(transports) else None
            ),
        )
        for i, cred_id in enumerate(credential_ids)
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
    """Verifies the authentication response.

    Returns the new sign_count.
    Raises ValueError on failure or suspected cloning (sign count regression).
    """
    domain = _require_domain()
    try:
        verification = verify_authentication_response(
            credential=credential_json,
            expected_challenge=challenge,
            expected_rp_id=domain,
            expected_origin=_ORIGIN,
            credential_public_key=stored_public_key,
            credential_current_sign_count=stored_sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        raise ValueError(f"Authentication failed: {exc}") from exc

    new_count = verification.new_sign_count
    # Strict check: replay / clone protection
    if stored_sign_count > 0 and new_count <= stored_sign_count:
        raise ValueError(
            f"Sign count regression: stored={stored_sign_count}, "
            f"new={new_count}. Possible authenticator clone."
        )

    return new_count
