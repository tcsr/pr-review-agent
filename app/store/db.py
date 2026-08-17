from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.store.tables import Base


def make_engine(url: str):
    connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, future=True)


def init_db(engine):
    Base.metadata.create_all(engine)
