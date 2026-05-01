from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import AppConfig


class Base(DeclarativeBase):
    pass


def create_engine_from_config(config: AppConfig):
    return create_engine(config.postgres.sqlalchemy_url(), future=True, pool_pre_ping=True)


def create_session_factory(config: AppConfig) -> sessionmaker:
    engine = create_engine_from_config(config)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
