"""
Database connection.

Using SQLite for zero-setup speed. To move to PostgreSQL later
(matching the project's proposed architecture), the ONLY thing that
changes is DATABASE_URL below, e.g.:

    DATABASE_URL = "postgresql://user:password@localhost:5432/arthpulse"

No query code anywhere else needs to change.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./arthpulse.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
