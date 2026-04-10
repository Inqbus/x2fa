from flask import Flask, g

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from x2fa.models import Base

from x2fa.config import cfg


engine = create_engine(cfg.x2fa_db.SQLALCHEMY_DATABASE_URI)
SessionFactory = sessionmaker(bind=engine)

def database(app: Flask):
    database_creation(app)
    database_migration(app)
    database_session(app)


def database_creation(app: Flask):
    # Create database tables
    # THis is important to guarantee that the models are availabe
    import x2fa.models

    if app.config.x2fa.TESTING:
        Base.metadata.create_all(engine)

def database_migration(app: Flask):
    """To be implemented"""

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
