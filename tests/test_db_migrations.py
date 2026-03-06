from __future__ import annotations

from sqlalchemy import text

from sentinelfi.core.config import Settings
from sentinelfi.repositories.db import init_db, session_scope


def test_init_db_runs_alembic_migrations(tmp_path) -> None:
    db_path = tmp_path / "migrated.db"
    settings = Settings(database_url=f"sqlite:///{db_path}")

    init_db(settings)

    expected_tables = {
        "auditrun",
        "findingrecord",
        "gstrecord",
        "cleanuptaskrecord",
        "classifiedtxrecord",
        "feedbackrecord",
        "modeltrainingrun",
        "auditjobrecord",
        "appsettingrecord",
        "scheduledauditrecord",
        "alembic_version",
    }

    with session_scope(settings) as session:
        rows = session.exec(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
        table_names = {str(row[0]) for row in rows}

    assert expected_tables.issubset(table_names)
