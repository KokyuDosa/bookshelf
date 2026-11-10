"""Apply numbered schema/###_*.sql files, tracked by PRAGMA user_version."""

import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from bookshelf.paths import SCHEMA_DIR

MIGRATION_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


class MigrationError(Exception):
    pass


def discover(schema_dir: Path = SCHEMA_DIR) -> list[tuple[int, Path]]:
    """Return (version, path) pairs, sorted and checked to e 1..n with no gaps."""
    found = []
    for path in schema_dir.glob("*.sql"):
        match = MIGRATION_NAME.match(path.name)
        if match: # other files (snapshot.sql) are ignored
            found.append((int(match.group(1)), path))

    found.sort()
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"migration numbers must run 1..n without gaps or repeates: {versions}")
    return found

def backup(conn: sqlite3.Connection, db_path: Path, version: int) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = db_path.parent / "backups" / f"{db_path.stem}-v{version}-{stamp}.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(dest)) as target: # 'with connect()' alone does NOT close
        conn.backup(target)
    return dest

def migrate(db_path: Path, schema_dir: Path = SCHEMA_DIR) -> tuple[int, int]:
    """Bring db_path up to the newest migration. Returns (old_version, new_version)."""
    files = discover(schema_dir)
    latest = files[-1][0] if files else 0

    # autocommit=True: the sqlite3 module never opens or commits transactions on its own,
    # so the BEGIN/COMMIT below are the only ones, and the executescript() won't commit early
    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute("PRAGMA foreign_keys = OFF") # muyst be outside a transaction
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current > latest:
            raise MigrationError(
                f"database is at version {current}, newer than this code knows ({latest})"
            )

        pending = [(v, p) for v, p in files if v > current]
        if not pending:
            return current, current
        if current > 0:
            backup(conn, db_path, current)

        for version, path in pending:
            conn.execute("BEGIN")
            try:
                conn.executescript(path.read_text(encoding="utf=8"))
                problems = conn.execute("PRAGMA foreign_key_check").fetchall()
                if problems:
                    raise MigrationError(f"{path.name} broke foreign keys: {problems[:5]}")
                conn.execute(f"PRAGMA user_version = {version:d}") # pragmas take no ? parameters
                conn.execute("COMMIT")

            except Exception as e:
                conn.execute("ROLLBACK")
                raise MigrationError(f"{path.name} failed and was rolled back: {e}") from e


        return current, pending[-1][0]
