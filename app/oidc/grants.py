import time
from datetime import datetime, timezone, timedelta

from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core.grants import OpenIDCode

from app.extensions import db
from app.models import AuthorizationCode, OIDCClient, SigningKey


class S256OnlyCodeChallenge(CodeChallenge):
    """Erlaubt ausschließlich S256 – plain ist explizit blockiert."""
    SUPPORTED_CODE_CHALLENGE_METHOD = ["S256"]


class X2FAAuthorizationCodeGrant(AuthorizationCodeGrant):
    """OIDC Authorization Code Grant mit PKCE S256."""

    TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_post", "client_secret_basic"]

    def save_authorization_code(self, code, request):
        user_id = request.user  # gesetzt durch create_authorization_response(grant_user=...)
        payload = request.payload
        auth_code = AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            user_id=user_id,
            redirect_uri=(
                payload.redirect_uri or request.client.get_default_redirect_uri()
            ),
            scope=payload.scope,
            nonce=payload.data.get("nonce"),
            code_challenge=payload.data.get("code_challenge"),
            code_challenge_method="S256",
            auth_time=int(time.time()),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        db.session.add(auth_code)
        db.session.commit()
        return auth_code

    def query_authorization_code(self, code, client):
        auth_code = AuthorizationCode.query.filter_by(
            code=code,
            client_id=client.client_id,
        ).first()
        if not auth_code or auth_code.is_expired() or auth_code.used:
            return None
        return auth_code

    def delete_authorization_code(self, authorization_code):
        """Markiert als verbraucht (kein physisches Löschen – Nonce-Schutz)."""
        authorization_code.used = True
        db.session.commit()

    def authenticate_user(self, authorization_code):
        return authorization_code.user_id


class X2FAOpenIDCode(OpenIDCode):
    """OpenIDCode-Extension: ID-Token (ES256) + Nonce-Replay-Schutz."""

    def exists_nonce(self, nonce, request):
        if not nonce:
            return False
        return AuthorizationCode.query.filter_by(nonce=nonce).first() is not None

    def get_jwt_config(self, grant):
        from flask import current_app
        from app.services.crypto import CryptoService

        crypto = CryptoService(current_app.config["X2FA_SECRET"])
        signing_key = (
            SigningKey.query
            .filter(
                SigningKey.active == True,
                db.or_(
                    SigningKey.expires_at == None,
                    SigningKey.expires_at > datetime.now(timezone.utc),
                ),
            )
            .order_by(SigningKey.created_at.desc())
            .first()
        )
        if not signing_key:
            raise RuntimeError(
                "Kein aktiver Signing-Key vorhanden. 'flask init-keys' ausführen."
            )
        private_key = signing_key.get_private_key(crypto.get_fernet())
        domain = current_app.config["X2FA_DOMAIN"]
        return {
            "key": private_key,
            "alg": signing_key.algorithm,
            "iss": f"https://{domain}",
            "exp": 60,
            "kid": signing_key.kid,
        }

    def generate_user_info(self, user, scope):
        return {"sub": user}


def query_client(client_id: str):
    return OIDCClient.query.filter_by(client_id=client_id, active=True).first()


def save_token(token, request):
    """No-op: Access Tokens sind stateless JWTs, kein DB-Eintrag nötig."""
    pass
