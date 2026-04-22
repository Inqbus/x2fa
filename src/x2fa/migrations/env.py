"""Alembic environment — wired to x2fa's SQLAlchemy Base.metadata.

Does NOT depend on Flask-Migrate. The DB URL is read from the x2fa
config pool or can be
overridden on the Alembic command line with -x sqlalchemy.url=<url>.
"""

import os
import sys
from pathlib import Path

from x2fa.init_app.config import load_config

# Make the src layout importable when running the alembic CLI directly.
# __file__ = src/x2fa/migrations/env.py → parent.parent.parent = src/
_src = str(Path(__file__).resolve().parent.parent.parent)
if _src not in sys.path:
    sys.path.insert(0, _src)

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# Import all models so their tables are registered on Base.metadata.
from x2fa.model import Base  # noqa: F401 — side-effect import registers all tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _db_url() -> str:
    """Return the database URL.

    Priority:
    1. ``-x sqlalchemy.url=<url>`` passed on the Alembic CLI
    2. ``sqlalchemy.url`` set in alembic.ini [alembic] section
    """
    # -x key=value arguments are read via context.get_x_argument()
    x_args = context.get_x_argument(as_dictionary=True)
    if "sqlalchemy.url" in x_args:
        return x_args["sqlalchemy.url"]

    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url

    return load_config().x2fa_database.SQLALCHEMY_DATABASE_URI


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL)."""
    context.configure(
        url=_db_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = create_engine(_db_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
