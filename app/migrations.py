from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.config import AppConfig
from app.db import create_engine_from_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI_PATH = PROJECT_ROOT / "alembic.ini"


class SchemaVersionError(RuntimeError):
    pass


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI_PATH))


def migration_head() -> str:
    script = ScriptDirectory.from_config(alembic_config())
    return script.get_current_head()


def apply_migrations() -> None:
    command.upgrade(alembic_config(), "head")


def assert_database_at_head(connection, expected_head: str) -> None:
    context = MigrationContext.configure(connection)
    current_revision = context.get_current_revision()
    if current_revision is None:
        raise SchemaVersionError(
            "Database schema is not initialized. Run `python -m app migrate` before starting the service."
        )
    if current_revision != expected_head:
        raise SchemaVersionError(
            f"Database schema revision {current_revision!r} is not current; expected {expected_head!r}. "
            "Run `python -m app migrate`."
        )


def verify_schema_current(config: AppConfig) -> None:
    expected_head = migration_head()
    engine = create_engine_from_config(config)
    try:
        with engine.connect() as connection:
            assert_database_at_head(connection, expected_head)
    finally:
        engine.dispose()
