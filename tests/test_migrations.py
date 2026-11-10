import shutil
import sqlite3
from contextlib import closing

import pytest

from bookshelf import migrations
from bookshelf.db import connect
from bookshelf.paths import SCHEMA_DIR


def version(path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


def test_fresh_build_reaches_latest(tmp_path):
    db = tmp_path / "b.db"
    old, new = migrations.migrate(db)
    assert (old, new) == (0, migrations.discover()[-1][0])
    assert version(db) == new


def test_second_run_does_nothing(tmp_path):
    db = tmp_path / "b.db"
    migrations.migrate(db)
    old, new = migrations.migrate(db)
    assert old == new
    assert not (tmp_path / "backups").exists()  # nothing applied, nothing backed up


def test_upgrade_keeps_data_and_backs_up(tmp_path):
    schema = tmp_path / "schema"
    schema.mkdir()
    shutil.copy(SCHEMA_DIR / "001_init.sql", schema)
    db = tmp_path / "b.db"
    migrations.migrate(db, schema)
    with closing(connect(db)) as conn, conn:
        conn.execute("INSERT INTO series (name, name_key) VALUES ('Discworld', 'discworld')")

    (schema / "002_add_wishlist.sql").write_text(
        "CREATE TABLE wishlist (wish_id INTEGER PRIMARY KEY, title TEXT NOT NULL) STRICT;",
        encoding="utf-8",
    )
    assert migrations.migrate(db, schema) == (1, 2)
    with closing(connect(db)) as conn:
        assert conn.execute("SELECT name FROM series").fetchone()[0] == "Discworld"
    backups = list((tmp_path / "backups").glob("b-v1-*.db"))
    assert len(backups) == 1 and version(backups[0]) == 1


def test_database_newer_than_code_is_refused(tmp_path):
    db = tmp_path / "b.db"
    migrations.migrate(db)
    with closing(sqlite3.connect(db)) as conn:
        conn.execute("PRAGMA user_version = 99")
    with pytest.raises(migrations.MigrationError, match="newer"):
        migrations.migrate(db)


@pytest.mark.parametrize(
    "names", [["001_a.sql", "003_c.sql"], ["002_b.sql"], ["001_a.sql", "001_b.sql"]]
)
def test_gaps_and_repeats_are_refused(tmp_path, names):
    for name in names:
        (tmp_path / name).write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(migrations.MigrationError, match="without gaps"):
        migrations.discover(tmp_path)


def test_other_sql_files_are_ignored(tmp_path):
    (tmp_path / "001_init.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "snapshot.sql").write_text("SELECT 1;", encoding="utf-8")
    assert [v for v, _ in migrations.discover(tmp_path)] == [1]


def test_schema_matches_committed_snapshot(db):
    """Fails whenever the schema changes; run `bookshelf snapshot` and commit the diff."""
    committed = (SCHEMA_DIR / "snapshot.sql").read_text("utf-8").replace("\r\n", "\n")
    assert migrations.schema_snapshot(db) == committed
