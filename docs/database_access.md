Hier ist ein Entwurf, der alle drei Kontexte (Web, CLI, Tests) sauber trennt – ohne globale Module-State, mit klarer Lebenszykluskontrolle:

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
        self._local = threading.local()  # Für CLI-Thread-Isolation
    
    def configure(self, uri: str, **engine_kwargs):
        """Einmalig zur App-Initialisierung"""
        self.engine = create_engine(uri, **engine_kwargs)
        self._Session = sessionmaker(bind=self.engine)
        
        # Für SQLite-Tests: ensure foreign keys
        if self.engine.dialect.name == 'sqlite':
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    
    def init_app(self, app):
        """Bindet sich in Flask-Request-Lifecycle ein"""
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
        Nur für Web-Requests! 
        Zugriff auf die aktive Request-Session via Flask g.
        """
        if not has_request_context():
            raise RuntimeError(
                "Außerhalb eines Request-Kontexts. "
                "Verwende 'with db.session_scope():' für CLI/Tests"
            )
        return g._db_session
    
    @contextmanager
    def session_scope(self, bind=None):
        """
        Für CLI-Tools und Background-Jobs.
        Automatisches Commit/Rollback, Thread-sicher.
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
        Für Pytest-Fixtures.
        Startet eine verschachtelte Transaktion (Savepoint), 
        die am Ende automatisch rollbacked.
        
        Usage:
            @pytest.fixture
            def db_session(database):
                with database.test_transaction() as s:
                    yield s
        """
        conn = self.engine.connect()
        trans = conn.begin()
        
        # Session an Connection binden (nicht Engine), damit wir 
        # die Transaktion kontrollieren können
        session = self._Session(bind=conn)
        
        # Für PostgreSQL/MySQL: Beginne Savepoint für ORM-Operationen
        if self.engine.dialect.name != 'sqlite':
            session.begin_nested()
        
        try:
            yield session
        finally:
            session.close()
            trans.rollback()
            conn.close()
    
    def reset_schema(self):
        """Hilfsmethode für Tests: Drop & Create all tables"""
        from x2fa.models import Base
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)
```

### Verwendung

**1. Web (normal):**
```python
@app.route('/users')
def list_users():
    # Automatisch via Flask g, geschlossen nach Request
    users = db.session.query(User).all()
    return render_template('users.html', users=users)
```

**2. CLI-Tools:**
```python
@click.command()
def initdb():
    """Funktioniert ohne Flask-Request-Context"""
    with db.session_scope() as session:
        # Explizite Session, wird committed am Ende
        admin = User(name="admin")
        session.add(admin)

@click.command()
def complex_workflow():
    """Mehrere Operationen in einer Transaktion"""
    with db.session_scope() as session:
        do_step1(session)
        do_step2(session)
        # Commit erst hier, bei Exception automatisch Rollback
```

**3. Tests (mit Fixtures):**
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
    """Jeder Test läuft in isolierter Transaktion"""
    with database.test_transaction() as session:
        yield session
    # Auto-rollback hier, DB bleibt clean für nächsten Test

@pytest.fixture
def sample_user(db_session):
    """Fixture baut Test-Daten auf"""
    user = User(name="Testuser", email="test@example.com")
    db_session.add(user)
    db_session.flush()  # ID generieren ohne Commit
    return user

def test_user_model(database, sample_user):
    # Wenn du einen Request simulierst (Flask test_client):
    with app.test_request_context():
        # db.session ist jetzt verfügbar und identisch mit test-transaction
        # wenn du bind_to_transaction verwendest (siehe unten)
        pass
    
    # Oder direkt mit der Session arbeiten:
    assert sample_user.id is not None
    result = database.engine.execute("SELECT count(*) FROM users").scalar()
    assert result == 1
    # Nach dem Test: alles weg durch rollback
```

### Erweiterung: Test-Integration mit Flask-Test-Client

Wenn du `test_client()` nutzen willst, aber die DB-Änderungen des Fixtures im Request sichtbar sein sollen (gleiche Transaktion):

```python
@pytest.fixture
def app(database):
    app = create_app(testing=True)
    app.extensions['sqlalchemy'] = database  # Deine DB-Instanz
    
    # Patch: Test-Client nutzt gleiche Connection/Transaktion
    @app.before_request
    def bind_test_session():
        if hasattr(g, '_test_session'):
            g._db_session = g._test_session
    
    return app

def test_api(app, database, db_session):
    # db_session ist deine Test-Fixture-Session
    user = User(name="API User")
    db_session.add(user)
    db_session.flush()
    
    # Mach diese Session für den Request verfügbar
    with app.test_request_context():
        g._test_session = db_session
        with app.test_client() as client:
            resp = client.get(f'/api/users/{user.id}')
            assert resp.status_code == 200
```

**Vorteile dieser Lösung:**
- **Kein globaler State**: `_engine` und `SessionFactory` sind Instanzvariablen
- **Explizite Scopes**: Web (implizit), CLI (explizit), Tests (transaktional)
- **Thread-Sicher**: CLI nutzt `session_scope` mit lokalem Kontext
- **Schnelle Tests**: `test_transaction` nutzt Savepoints (keine DB-Reset zwischen Tests nötig)

Möchtest du die Test-Integration mit Factory-Boy oder ähnlichen Fixture-Generatoren kombinieren?