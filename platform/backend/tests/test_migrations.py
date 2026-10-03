"""Versioned schema migrations: fresh databases, adopting pre-migration schemas and refusing stale ones."""

from __future__ import annotations

from dataclasses import replace

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from app import main
from app.core import config, database, migrate
from app.models import Base


@pytest.fixture(autouse=True)
def keep_test_logging(monkeypatch):
    # startup() and the migrate command configure process-wide logging; keep pytest's capture intact.
    monkeypatch.setattr(main, "configure_logging", lambda *_args: None)
    monkeypatch.setattr(migrate, "configure_logging", lambda *_args: None)


def file_engine(tmp_path, name="platform.sqlite"):
    return database.make_engine(f"sqlite:///{tmp_path / name}")


def schema_diff(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)


def test_migrations_build_exactly_the_model_schema_and_rerun_as_a_no_op(tmp_path):
    engine = file_engine(tmp_path)
    assert migrate.upgrade(engine) == f"Database schema upgraded from empty to {migrate.head_revision()}"
    assert schema_diff(engine) == []
    assert migrate.upgrade(engine) == f"Database schema is up to date ({migrate.head_revision()})"
    migrate.require_head(engine)
    engine.dispose()


def test_schema_created_before_migrations_is_adopted_not_recreated(tmp_path):
    engine = file_engine(tmp_path)
    database.init_db(engine)  # what earlier releases did at startup
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO workspaces (id, name, created_at) VALUES ('w1', 'Kept', '2026-01-01')"))
    message = migrate.upgrade(engine)
    assert message.startswith(f"Adopted the existing schema at revision {migrate.head_revision()}")
    assert migrate.current_revision(engine) == migrate.head_revision()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM workspaces")).scalar_one() == "Kept"
    engine.dispose()


def test_baseline_schema_is_stamped_then_upgraded(tmp_path):
    engine = file_engine(tmp_path)
    database.init_db(engine)
    with engine.begin() as connection:  # a database from before the login-throttling revision
        connection.execute(text("DROP TABLE login_attempts"))
    assert migrate.upgrade(engine).startswith(f"Adopted the existing schema at revision {migrate.BASELINE_REVISION}")
    assert "login_attempts" in inspect(engine).get_table_names()
    assert schema_diff(engine) == []
    engine.dispose()


def test_unrecognised_schema_without_history_is_refused(tmp_path):
    engine = file_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE workspaces (id VARCHAR(36) PRIMARY KEY)"))
    with pytest.raises(migrate.SchemaError, match="does not match the baseline schema"):
        migrate.upgrade(engine)
    assert migrate.current_revision(engine) is None
    engine.dispose()


def test_api_without_auto_migrate_refuses_an_unmigrated_database(tmp_path, monkeypatch):
    engine = file_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(config, "settings", replace(config.settings, auto_migrate=False, object_store_backend="local"))
    with pytest.raises(migrate.SchemaError, match="Run the migrate job"):
        main.startup()
    assert migrate.main(["--check"]) == 1
    engine.dispose()


def test_migrate_command_upgrades_then_checks(tmp_path, monkeypatch):
    engine = file_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)
    assert migrate.main([]) == 0
    assert migrate.main(["--check"]) == 0
    engine.dispose()
