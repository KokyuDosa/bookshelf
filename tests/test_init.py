import sqlite3
from contextlib import closing

from bookshelf.cli import main
from bookshelf.migrations import discover

LATEST = discover()[-1][0]


def test_init_creates_db_at_latest_version(tmp_path):
    db = tmp_path / "books.db"
    assert main(["--db", str(db), "init"]) == 0
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST
        assert conn.execute("SELECT count(*) FROM formats").fetchone()[0] > 0


def test_init_refuses_existing_db(tmp_path):
    db = tmp_path / "books.db"
    main(["--db", str(db), "init"])
    assert main(["--db", str(db), "init"]) == 1


def test_migrate_twice_is_a_noop(tmp_path, capsys):
    db = tmp_path / "books.db"
    main(["--db", str(db), "init"])
    assert main(["--db", str(db), "migrate"]) == 0
    assert f"Already at version {LATEST}" in capsys.readouterr().out


def test_version_1_database_upgrades_to_2(tmp_path, capsys):
    """Your real books.db is at version 1 after the TTRPG import; migrate must add api_cache."""
    import shutil

    from bookshelf import migrations
    from bookshelf.paths import SCHEMA_DIR

    only_v1 = tmp_path / "schema"
    only_v1.mkdir()
    shutil.copy(SCHEMA_DIR / "001_init.sql", only_v1)
    db = tmp_path / "books.db"
    migrations.migrate(db, only_v1)
    assert main(["--db", str(db), "migrate"]) == 0
    assert "Migrated 1 -> 2" in capsys.readouterr().out
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT count(*) FROM api_cache").fetchone()[0] == 0
