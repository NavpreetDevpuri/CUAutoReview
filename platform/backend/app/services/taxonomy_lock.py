"""Transaction-scoped serialization for workspace taxonomy changes."""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session


def lock_taxonomy_workspace(session: Session, workspace_id: str) -> None:
    """Serialize taxonomy writers and approval checks on PostgreSQL.

    SQLite's write transaction already serializes the local single-process test/dev case.
    The lock is advisory and transaction-scoped, so callers must keep the write in the
    same transaction and must release it before any slow model/provider request.
    """
    if session.bind and session.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(workspace_id.encode()).digest()[:8], "big", signed=True)
        session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
