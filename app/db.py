"""
app/db.py — SQLAlchemy engine, session, and table initialisation.
"""

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import Config

engine = create_engine(
    Config.SQLALCHEMY_DATABASE_URI,
    connect_args={"check_same_thread": False},  # required for SQLite with Flask threads
    echo=False,
)

_SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


@contextmanager
def get_session():
    """Context-manager that yields a session and handles commit/rollback/close."""
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Create all tables if they do not already exist."""
    import app.models  # noqa: F401 — registers models on Base
    Base.metadata.create_all(bind=engine)
