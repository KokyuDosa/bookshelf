from contextlib import closing

import pytest

from bookshelf import migrations
from bookshelf.db import connect
from bookshelf.seed import seed


@pytest.fixture
def db_path(tmp_path):
    """A freshly migrated, empty database file."""
    path = tmp_path / "books.db"
    migrations.migrate(path)
    return path


@pytest.fixture
def db(db_path):
    with closing(connect(db_path)) as conn:
        yield conn


@pytest.fixture
def seeded(db):
    seed(db)
    return db
