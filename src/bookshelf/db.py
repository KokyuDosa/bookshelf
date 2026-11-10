"""The one place application code opens the database."""

import sqlite3
from pathlib import Path


def connect(path: Path | str) -> sqlite3.Connection:
    """Open the database with foreign keys enforced and rows readable by column name.

    Uses the module's default transaction handling: a transaction opens implicitly before the
    first INSERT/UPDATE/DELETE, and `with conn:` commits it (or rolls back on an exception).
    The foreign_keys pragma must run before any transaction opens, which is why it's here.
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn
