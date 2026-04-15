Here is a design that cleanly separates all three contexts (web, CLI, tests) — no global module state, with explicit lifecycle control:

```python
from contextlib import contextmanager
from flask import g, has_request_context, current_app
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
import threading

class Database:
    def __init__(self):
        self.engine = None
        self._Session = None
        self._local = threading.local()  # Thread isolation for CLI

    def configure(self, uri: str, **engine_kwargs):
        """Called once during app initialization."""
        self.engine = create_engine(uri, **engine_kwargs)
        self._Session = sessionmaker(bind=self.engine)

        # For SQLite tests: ensure foreign keys
        if self.engine.dialect.name == 'sqlite':
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    def init_app(self, app):
        """Hooks into the Flask request lifecycle."""
        if self.engine is None:
            raise RuntimeError("Call configure() before init_app()")

        @app.before_request
        def open_session():
            g._db_session = self._Session()

        @app.teardown_appcontext
        def close_session(exc):
            session = g.pop('_db_session', None)
            if session:
                if exc:
                    session.rollback()
                else:
                    session.commit()
                session.close()

    @property
    def session(self) -> Session:
        """
        For web requests only!
        Accesses the active request-scoped session via Flask g.
        """
        if not has_request_context():
            raise RuntimeError(
                "Outside of a request context. "
                "Use 'with db.session_scope():' for CLI/tests."
            )
        return g._db_session

    @contextmanager
    def session_scope(self, bind=None):
        """
        For CLI tools and background jobs.
        Automatic commit/rollback, thread-safe.
        """
        session = self._Session(bind=bind)
        token = getattr(self._local, 'token', 0) + 1
        self._local.token = token

        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
            if getattr(self._local, 'token', None) == token:
                delattr(self._local, 'token')

    @contextmanager
    def test_transaction(self):
        """
        For pytest fixtures.
        Starts a nested transaction (savepoint) that is automatically
        rolled back at the end.

        Usage:
            @pytest.fixture
            def db_session(database):
                with database.test_transaction() as s:
                    yield s
        """
        conn = self.engine.connect()
        trans = conn.begin()

        # Bind session to the connection (not the engine) so we control the transaction
        session = self._Session(bind=conn)

        # For PostgreSQL/MySQL: begin a savepoint for ORM operations
        if self.engine.dialect.name != 'sqlite':
            session.begin_nested()

        try:
            yield session
        finally:
            session.close()
            trans.rollback()
            conn.close()

    def reset_schema(self):
        """Helper for tests: drop and recreate all tables."""
        from x2fa.models import Base
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
```

### Usage

**1. Web (normal):**
```python
@app.route('/users')
def list_users():
    # Automatically managed via Flask g, closed after the request
    users = db.session.query(User).all()
    return render_template('users.html', users=users)
```

**2. CLI tools:**
```python
@click.command()
def initdb():
    """Works without a Flask request context."""
    with db.session_scope() as session:
        # Explicit session, committed at the end
        admin = User(name="admin")
        session.add(admin)

@click.command()
def complex_workflow():
    """Multiple operations in a single transaction."""
    with db.session_scope() as session:
        do_step1(session)
        do_step2(session)
        # Committed here; automatic rollback on exception
```

**3. Tests (with fixtures):**
```python
import pytest

@pytest.fixture(scope='session')
def database():
    db = Database()
    db.configure("sqlite:///:memory:", poolclass=StaticPool,
                 connect_args={"check_same_thread": False})
    db.reset_schema()
    return db

@pytest.fixture
def db_session(database):
    """Each test runs in an isolated transaction."""
    with database.test_transaction() as session:
        yield session
    # Auto-rollback here; DB stays clean for the next test

@pytest.fixture
def sample_user(db_session):
    """Fixture builds test data."""
    user = User(name="Testuser", email="test@example.com")
    db_session.add(user)
    db_session.flush()  # Generate ID without committing
    return user

def test_user_model(database, sample_user):
    # Simulating a request (Flask test_client):
    with app.test_request_context():
        # db.session is now available and shares the test transaction
        # when bind_to_transaction is used (see below)
        pass

    # Or work directly with the session:
    assert sample_user.id is not None
    result = database.engine.execute("SELECT count(*) FROM users").scalar()
    assert result == 1
    # After the test: everything gone via rollback
```

### Extension: test integration with Flask test client

If you want to use `test_client()` but have DB changes from fixtures visible inside the request (same transaction):

```python
@pytest.fixture
def app(database):
    app = create_app(testing=True)
    app.extensions['sqlalchemy'] = database  # Your DB instance

    # Patch: test client uses the same connection/transaction
    @app.before_request
    def bind_test_session():
        if hasattr(g, '_test_session'):
            g._db_session = g._test_session

    return app

def test_api(app, database, db_session):
    # db_session is your test fixture session
    user = User(name="API User")
    db_session.add(user)
    db_session.flush()

    # Make this session available to the request
    with app.test_request_context():
        g._test_session = db_session
        with app.test_client() as client:
            resp = client.get(f'/api/users/{user.id}')
            assert resp.status_code == 200
```

**Advantages of this design:**
- **No global state**: `_engine` and `SessionFactory` are instance variables
- **Explicit scopes**: Web (implicit), CLI (explicit), Tests (transactional)
- **Thread-safe**: CLI uses `session_scope` with a local context
- **Fast tests**: `test_transaction` uses savepoints (no DB reset between tests needed)
