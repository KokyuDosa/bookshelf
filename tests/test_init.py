import sqlite3
from contextlib import closing

from bookshelf.cli import main


def test_init_creates_db_at_latest_version(tmp_path):
    db = tmp_path / "books.db"
    assert main(["--db", str(db), "init"]) == 0
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM formats").fetchone()[0] > 0


def test_init_refuses_existing_db(tmp_path):
    db = tmp_path / "books.db"
    main(["--db", str(db), "init"])
    assert main(["--db", str(db), "init"]) == 1


def test_migrate_twice_is_a_noop(tmp_path, capsys):
    db = tmp_path / "books.db"
    main(["--db", str(db), "init"])
    assert main(["--db", str(db), "migrate"]) == 0
    assert "Already at version 1" in capsys.readouterr().out
