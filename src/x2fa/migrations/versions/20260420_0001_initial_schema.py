"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-04-20

Creates all tables for the initial x2fa schema.
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_log",
        sa.Column("id",        sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column("user_id",   sa.String(255),  nullable=False),
        sa.Column("action",    sa.String(50),   nullable=False),
        sa.Column("method",    sa.String(50),   nullable=False),
        sa.Column("ip_hash",   sa.String(64),   nullable=False),
        sa.Column("timestamp", sa.DateTime(),   nullable=False),
    )
    op.create_index("ix_audit_log_user_id",   "audit_log", ["user_id"])
    op.create_index("ix_audit_log_action",    "audit_log", ["action"])
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])

    op.create_table(
        "backup_code",
        sa.Column("code_hash",  sa.String(255), primary_key=True),
        sa.Column("user_id",    sa.String(255), nullable=False),
        sa.Column("used_at",    sa.DateTime(),  nullable=False),
        sa.Column("created_at", sa.DateTime(),  nullable=False),
    )
    op.create_index("ix_backup_code_user_id", "backup_code", ["user_id"])

    op.create_table(
        "challenge",
        sa.Column("challenge_id", sa.String(255),    primary_key=True),
        sa.Column("user_id",      sa.String(255),    nullable=False),
        sa.Column("challenge",    sa.LargeBinary(),  nullable=False),
        sa.Column("expires_at",   sa.DateTime(),     nullable=False),
        sa.Column("used",         sa.Boolean(),      nullable=False),
    )
    op.create_index("ix_challenge_user_id",   "challenge", ["user_id"])
    op.create_index("ix_challenge_expires_at","challenge", ["expires_at"])

    op.create_table(
        "credential",
        sa.Column("credential_id",     sa.LargeBinary(), primary_key=True),
        sa.Column("user_id",           sa.String(255),   nullable=False),
        sa.Column("public_key",        sa.LargeBinary(), nullable=False),
        sa.Column("sign_count",        sa.Integer(),     nullable=False),
        sa.Column("authenticator_type",sa.String(20),    nullable=False),
        sa.Column("device_type",       sa.String(20),    nullable=False),
        sa.Column("transport",         sa.String(50),    nullable=False),
        sa.Column("is_passkey",        sa.Boolean(),     nullable=False),
        sa.Column("created_at",        sa.DateTime(),    nullable=False),
        sa.Column("last_used_at",      sa.DateTime(),    nullable=False),
    )
    op.create_index("ix_credential_user_id",           "credential", ["user_id"])
    op.create_index("idx_cred_user_created",           "credential", ["user_id", "created_at"])

    op.create_table(
        "oidc_client",
        sa.Column("client_id",                sa.String(255),   primary_key=True),
        sa.Column("redirect_uris",            sa.Text(),        nullable=False),
        sa.Column("allowed_scopes",           sa.String(255),   nullable=False),
        sa.Column("active",                   sa.Boolean(),     nullable=False),
        sa.Column("created_at",               sa.DateTime(),    nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(50),  nullable=False),
        sa.Column("jwks_uri",                 sa.String(255),   nullable=True),
        sa.Column("client_cert_fingerprint",  sa.String(95),    nullable=True),
        sa.Column("client_secret_encrypted",  sa.LargeBinary(), nullable=True),
    )

    op.create_table(
        "authorization_code",
        sa.Column("id",                   sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column("code",                 sa.String(255),  nullable=False),
        sa.Column("client_id",            sa.String(255),  nullable=False),
        sa.Column("user_id",              sa.String(255),  nullable=False),
        sa.Column("redirect_uri",         sa.Text(),       nullable=False),
        sa.Column("scope",                sa.String(255),  nullable=False),
        sa.Column("nonce",                sa.String(255),  nullable=True),
        sa.Column("code_challenge",       sa.String(255),  nullable=False),
        sa.Column("code_challenge_method",sa.String(10),   nullable=False),
        sa.Column("auth_time",            sa.Integer(),    nullable=False),
        sa.Column("expires_at",           sa.DateTime(),   nullable=False),
        sa.Column("used",                 sa.Boolean(),    nullable=False),
    )
    op.create_index("ix_authorization_code_code",       "authorization_code", ["code"],       unique=True)
    op.create_index("ix_authorization_code_expires_at", "authorization_code", ["expires_at"])

    op.create_table(
        "signing_key",
        sa.Column("id",                    sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column("kid",                   sa.String(255),  nullable=False),
        sa.Column("private_key_encrypted", sa.LargeBinary(),nullable=False),
        sa.Column("public_key_pem",        sa.Text(),       nullable=False),
        sa.Column("algorithm",             sa.String(10),   nullable=False),
        sa.Column("active",                sa.Boolean(),    nullable=False),
        sa.Column("created_at",            sa.DateTime(),   nullable=False),
        sa.Column("expires_at",            sa.DateTime(),   nullable=False),
    )
    op.create_index("ix_signing_key_kid", "signing_key", ["kid"], unique=True)

    op.create_table(
        "totp_secret",
        sa.Column("user_id",          sa.String(255),   primary_key=True),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("verified",         sa.Boolean(),     nullable=False),
        sa.Column("created_at",       sa.DateTime(),    nullable=False),
        sa.Column("last_used_at",     sa.DateTime(),    nullable=False),
    )

    op.create_table(
        "trusted_ca",
        sa.Column("id",         sa.Integer(),    primary_key=True, autoincrement=True),
        sa.Column("name",       sa.String(100),  nullable=False),
        sa.Column("cert_pem",   sa.Text(),       nullable=False),
        sa.Column("active",     sa.Boolean(),    nullable=False),
        sa.Column("created_at", sa.DateTime(),   nullable=False),
        sa.Column("expires_at", sa.DateTime(),   nullable=True),
    )
    op.create_index("ix_trusted_ca_name", "trusted_ca", ["name"], unique=True)


def downgrade():
    op.drop_table("trusted_ca")
    op.drop_table("totp_secret")
    op.drop_table("signing_key")
    op.drop_table("authorization_code")
    op.drop_table("oidc_client")
    op.drop_table("credential")
    op.drop_table("challenge")
    op.drop_table("backup_code")
    op.drop_table("audit_log")
