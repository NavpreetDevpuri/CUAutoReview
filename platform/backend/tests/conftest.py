"""Shared test setup: each test gets an in-memory database, local artifact storage and an empty project root."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core import config, database
from app.main import app

ORIGIN = {"Origin": "http://testserver"}


@asynccontextmanager
async def no_lifespan(_app):
    yield


def isolate(tmp_path, patcher):
    """Point the API and the worker at a fresh database and tmp_path storage; returns the engine and session factory.

    ``patcher`` is pytest's ``monkeypatch`` (or one of its contexts), so every change is undone after the test.
    The production lifespan (schema creation, S3 bucket check, outbox loop) is skipped.
    """
    engine = database.make_engine("sqlite:///:memory:")
    factory = database.make_session_factory(engine)
    database.init_db(engine)
    patcher.setattr(database, "engine", engine)
    patcher.setattr(database, "SessionLocal", factory)
    patcher.setattr(
        config,
        "settings",
        replace(
            config.settings, seed_poc=False, object_store_backend="local", local_artifact_dir=tmp_path / "artifacts"
        ),
    )
    patcher.setattr(config, "PROJECT_ROOT", tmp_path)
    patcher.setattr(app.router, "lifespan_context", no_lifespan)
    return engine, factory


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    engine, factory = isolate(tmp_path, monkeypatch)
    yield {"engine": engine, "factory": factory, "tmp_path": tmp_path}
    engine.dispose()


# Signed-in admin client shared by the batch status and queue reliability tests.
@pytest.fixture
def batch_app(tmp_path, monkeypatch):
    engine, factory = isolate(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/signup", json={"name": "Admin", "email": "admin@example.test", "password": "test-password-123"}
        )
        assert response.status_code == 200, response.text
        yield {"client": client, "factory": factory, "tmp_path": tmp_path}
    engine.dispose()
