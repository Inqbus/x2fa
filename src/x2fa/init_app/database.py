from flask import Flask, g

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from x2fa.models import Base
from x2fa.config import cfg

# Initialised once on first create_app() call.
_engine = None
SessionFactory = None


def get_engine():
    return _engine


def database(app: Flask):
    global _engine, SessionFactory

    if _engine is None:
        uri = cfg.x2fa_db.SQLALCHEMY_DATABASE_URI
        url = make_url(uri)
        if url.drivername == "sqlite" and url.database in (None, "", ":memory:"):
            # StaticPool: all sessions share one connection so that an in-memory
            # database created by one session is visible to all others (including
            # the ones opened by the test fixtures that inspect the DB directly).
            _engine = create_engine(
                uri,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            _engine = create_engine(uri, pool_pre_ping=True)

        SessionFactory = sessionmaker(bind=_engine)

    # Ensure schema exists (idempotent — uses IF NOT EXISTS internally).
    Base.metadata.create_all(_engine)

    database_session(app)


def database_session(app: Flask):

    @app.before_request
    def before_request():
        g.db_session = SessionFactory()

    @app.teardown_appcontext
    def teardown(error):
        db_session = g.pop('db_session', None)
        if db_session is not None:
            if error:
                db_session.rollback()
            else:
                db_session.commit()
            db_session.close()
