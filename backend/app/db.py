from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Fail fast when the database cannot be reached (no internet), rather
    # than hang the request: offline.py takes over then.
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
