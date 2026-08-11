import sqlite3

import pytest

from athena.storage.database import SQLiteDatabase
from athena.storage.schema import (
    ATHENA_APPLICATION_ID,
    SCHEMA_VERSION,
    DatabaseCompatibilityError,
)


def test_database_initializes_required_pragmas_and_schema(tmp_path) -> None:
    database = SQLiteDatabase(tmp_path / "athena.db")
    database.start()

    connection = database.connection
    assert connection.execute("PRAGMA application_id").fetchone()[0] == ATHENA_APPLICATION_ID
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal"
    assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
    assert connection.execute("PRAGMA read_uncommitted").fetchone()[0] == 0
    assert connection.execute("PRAGMA trusted_schema").fetchone()[0] == 0

    database.stop()


def test_database_reopens_existing_schema(tmp_path) -> None:
    path = tmp_path / "athena.db"
    first = SQLiteDatabase(path)
    first.start()
    first.stop()

    second = SQLiteDatabase(path)
    second.start()

    assert second.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    second.stop()


def test_database_refuses_unrelated_nonempty_sqlite_file(tmp_path) -> None:
    path = tmp_path / "athena.db"
    foreign = sqlite3.connect(path)
    foreign.execute("CREATE TABLE foreign_data(value TEXT)")
    foreign.commit()
    foreign.close()

    database = SQLiteDatabase(path)

    with pytest.raises(DatabaseCompatibilityError, match="Refusing to adopt"):
        database.start()
