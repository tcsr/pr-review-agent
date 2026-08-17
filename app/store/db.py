from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.store.tables import Base


def _connect_args_for(url: str) -> dict:
    return {"timeout": 30} if url.startswith("sqlite") else {}


def make_engine(url: str):
    return create_engine(url, future=True, connect_args=_connect_args_for(url))


def make_session_factory(engine):
    return sessionmaker(bind=engine, future=True)


def init_db(engine):
    Base.metadata.create_all(engine)
