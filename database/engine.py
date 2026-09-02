"""SQLAlchemy engine and session management.

Creates the SQLite database at the configured path, runs migrations, and
ensures all tables exist. The whole schema is defined in :mod:`database.models`.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base
from database.migrations import init_database


class Database:
    def __init__(self, path: str) -> None:
        self.engine = init_database(path)
        self.Session = sessionmaker(bind=self.engine, future=True)

    def session(self):
        return self.Session()

    def dispose(self) -> None:
        self.engine.dispose()
