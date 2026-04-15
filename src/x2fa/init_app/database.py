from contextlib import contextmanager
from flask import Flask, g, has_request_context

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
import threading

from x2fa.models import Base
from x2fa.config import cfg


class Database:
    """Database connection manager with support for Web, CLI, and Test contexts."""

    def __init__(self):
        self.engine = None
        self._Session = None
        self._local = threading.local()
        self.is_configured = False

    def configure(self, uri: str, **engine_kwargs):
        """Configure database engine and session factory (once)."""
        url = make_url(uri)

        if url.drivername == "sqlite" and url.database in (None, "", ":memory:"):
            engine_kwargs.setdefault("connect_args", {"check_same_thread": False})
            engine_kwargs.setdefault("poolclass", StaticPool)

        self.engine = create_engine(uri, **engine_kwargs)
        self._Session = sessionmaker(bind=self.engine)

        if cfg.x2fa.ENV_FOR_DYNACONF == "testing":
            self.reset_schema()

        self.is_configured = True

    def init_app(self, app: Flask):
        """Bind database to Flask request lifecycle."""
        if not self.is_configured:
            self.configure(uri=cfg.x2fa_database.SQLALCHEMY_DATABASE_URI)

        @app.before_request
        def open_session():
            g.db_session = self._Session()

        @app.teardown_appcontext
        def close_session(exc):
            session = g.pop("db_session", None)
            if session:
                if exc:
                    session.rollback()
                else:
                    session.commit()
                session.close()

    @property
    def session(self) -> Session:
        """Get session from Flask request context."""
        if not has_request_context():
            raise RuntimeError(
                "Outside of request context. "
                "Use 'with db.session_scope()' for CLI or 'with db.test_transaction()' for tests."
            )
        return g.db_session

    @contextmanager
    def session_scope(self):
        """For CLI tools and background jobs. Auto-commit/rollback."""
        session = self._Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def test_transaction(self):
        """For pytest fixtures. Uses savepoint for auto-rollback."""
        conn = self.engine.connect()
        trans = conn.begin()
        session = self._Session(bind=conn)

        try:
            yield session
        finally:
            session.close()
            trans.rollback()
            conn.close()

    def reset_schema(self):
        """Drop and recreate all tables (for tests)."""
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)

db = Database()
