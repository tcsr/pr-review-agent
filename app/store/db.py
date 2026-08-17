from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.store.tables import Base


def make_engine(url: str):
    return create_engine(url, future=True)


def make_session_factory(engine):
    return sessionmaker(bind=engine, future=True)


def init_db(engine):
    Base.metadata.create_all(engine)
