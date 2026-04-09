from flask import Flask, g

from flask_migrate import Migrate

from sqlalchemy import create_engine
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm import sessionmaker, scoped_session

from x2fa.models import Base

migrate = Migrate()

def database(app: Flask):
    engine = database_engine(app)
    database_creation(app, engine)
    database_session(app, engine)

def database_engine(app: Flask):
    engine = create_engine(app.config.db.SQLALCHEMY_DATABASE_URI, pool_pre_ping = True)
    return engine

def database_creation(app: Flask, engine: Engine):
    # Create database tables
    if app.config.x2fa.TESTING:
        with app.app_context():
            Base.metadata.create_all(engine)

def database_migraton(app: Flask):
    """To be implemented"""

def database_session(app: Flask, engine: Engine):
    SessionFactory = sessionmaker(bind=engine)

    @app.before_request
    def before_request():
        g.db_session = scoped_session(SessionFactory)

    @app.teardown_appcontext
    def teardown(error):
        db_session = g.pop('db_session', None)
        if db_session is not None:
            if error:
                db_session.rollback()
            else:
                db_session.commit()
            db_session.remove()
