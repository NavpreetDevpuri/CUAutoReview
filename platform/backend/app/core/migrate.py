"""Schema migrations: create, adopt a legacy create_all schema, upgrade, or verify the database is at head.

Run as a one-shot job before starting the API in production: ``python -m app.core.migrate``.
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool

from app.core import config, database
from app.core.logs import configure_logging

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
# The revision that matches databases created by Base.metadata.create_all before migrations existed.
BASELINE_REVISION = "0001"
# Serializes concurrent migrate runs (several replicas or a job racing an app) on PostgreSQL.
ADVISORY_LOCK_KEY = 53325899261002

logger = logging.getLogger("cuautoreview.migrate")


class SchemaError(RuntimeError):
    """The database schema cannot be used by this release without operator action."""


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


@functools.cache
def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def _revision(connection: Connection) -> str | None:
    # A plain query rather than Alembic's MigrationContext, which logs on every call (readiness polls often).
    if not inspect(connection).has_table("alembic_version"):
        return None
    return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return _revision(connection)


def _table_columns(connection: Connection) -> dict[str, set[str]]:
    inspector = inspect(connection)
    return {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


def _schema_at(revision: str) -> dict[str, set[str]]:
    """Tables and columns that a revision defines, built in a throwaway in-memory database."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    try:
        with engine.begin() as connection:
            command.upgrade(alembic_config(connection), revision)
            return _table_columns(connection)
    finally:
        engine.dispose()


def _missing(expected: dict[str, set[str]], actual: dict[str, set[str]]) -> list[str]:
    missing = []
    for table, columns in sorted(expected.items()):
        if table not in actual:
            missing.append(table)
        else:
            missing.extend(f"{table}.{column}" for column in sorted(columns - actual[table]))
    return missing


def _adopt(connection: Connection) -> str:
    """Stamp a pre-migration schema with the newest revision it fully contains, or refuse."""
    actual = _table_columns(connection)
    head = head_revision()
    for revision in dict.fromkeys((head, BASELINE_REVISION)):
        if not _missing(_schema_at(revision), actual):
            command.stamp(alembic_config(connection), revision)
            return revision
    gaps = _missing(_schema_at(BASELINE_REVISION), actual)
    raise SchemaError(
        "The database has tables but no migration history, and it does not match the baseline schema "
        f"(missing: {', '.join(gaps[:12])}{' …' if len(gaps) > 12 else ''}). Restore a backup or migrate it manually."
    )


def upgrade(engine: Engine) -> str:
    """Bring the database to head and describe what happened. Safe to run repeatedly and concurrently."""
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": ADVISORY_LOCK_KEY})
        before = _revision(connection)
        adopted = None
        if before is None and _table_columns(connection):
            adopted = _adopt(connection)
        command.upgrade(alembic_config(connection), "head")
        after = _revision(connection)
    if adopted:
        return f"Adopted the existing schema at revision {adopted}; now at {after}"
    if before == after:
        return f"Database schema is up to date ({after})"
    return f"Database schema upgraded from {before or 'empty'} to {after}"


def require_head(engine: Engine) -> None:
    """Raise SchemaError unless the database is exactly at this release's head revision."""
    current, head = current_revision(engine), head_revision()
    if current != head:
        raise SchemaError(
            f"Database schema is at revision {current or 'none'} but this release requires {head}. "
            "Run the migrate job (`python -m app.core.migrate`, the compose `migrate` service) before starting."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only verify that the database is at head")
    args = parser.parse_args(argv)
    config.check_settings()
    configure_logging(config.settings.log_level, config.settings.log_format)
    try:
        if args.check:
            require_head(database.engine)
            message = f"Database schema is at head ({head_revision()})"
        else:
            message = upgrade(database.engine)
    except SchemaError as exc:
        logger.error("%s", exc)
        return 1
    logger.info("%s", message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
