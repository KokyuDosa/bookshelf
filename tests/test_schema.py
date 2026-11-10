"""The Schema Workbook's "Prove it" table: what the schema must refuse, and what it must do."""

import sqlite3

import pytest

from bookshelf import migrations


def add_book(db, title="A Book", **cols):
    """Insert a minimal valid book plus any extra columns; returns its book_id."""
    names = ["title", "sort_title", "title_key", "natural_key", *cols]
    values = [title, title, title.casefold(), title.casefold() + "||", *cols.values()]
    sql = f"INSERT INTO books ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})"
    return db.execute(sql, values).lastrowid


def add_author(db, key="tolkien j r r"):
    return db.execute(
        "INSERT INTO authors (display_name, sort_name, match_key) VALUES ('J.R.R. Tolkien', 'Tolkien, J.R.R.', ?)",
        (key,),
    ).lastrowid


def link(db, book_id, author_id, role="author", position=1):
    db.execute(
        "INSERT INTO book_authors (book_id, author_id, role, position) VALUES (?, ?, ?, ?)",
        (book_id, author_id, role, position),
    )


# 1
def test_connections_enforce_foreign_keys(db):
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# 2
def test_link_to_missing_book_fails(db):
    author = add_author(db)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        link(db, 999, author)


# 3
@pytest.mark.parametrize("title", ["", "   "])
def test_blank_title_fails(db, title):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_book(db, title)


# 4
def test_strict_typing_rejects_text_year(db):
    with pytest.raises(sqlite3.IntegrityError, match="cannot store TEXT"):
        add_book(db, pub_year="nineteen")


# 5
@pytest.mark.parametrize(
    "isbn", ["978-0306406157", "978030640615", "1234567890128", "97803064061X7"]
)
def test_malformed_isbn13_fails(db, isbn):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_book(db, isbn13=isbn)


def test_duplicate_isbn13_fails(db):
    add_book(db, "One", isbn13="9780306406157")
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_book(db, "Two", isbn13="9780306406157")


def test_many_books_without_isbn_are_fine(db):
    add_book(db, "One")
    add_book(db, "Two")  # NULLs never collide under UNIQUE


# 6
def test_duplicate_author_match_key_fails(db):
    add_author(db)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        add_author(db)


# 7
def test_duplicate_credit_fails(db):
    book, author = add_book(db), add_author(db)
    link(db, book, author)
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        link(db, book, author, position=2)


def test_same_person_in_two_roles_is_fine(db):
    book, author = add_book(db), add_author(db)
    link(db, book, author, "author", 1)
    link(db, book, author, "illustrator", 2)


# 8
def test_deleting_a_book_cascades(db):
    book, author = add_book(db), add_author(db)
    link(db, book, author)
    db.execute("INSERT INTO book_private (book_id, notes) VALUES (?, 'x')", (book,))
    db.execute("DELETE FROM books WHERE book_id = ?", (book,))
    assert db.execute("SELECT count(*) FROM book_authors").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM book_private").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM authors").fetchone()[0] == 1  # the person stays


# 9
def test_deleting_a_credited_author_fails(db):
    book, author = add_book(db), add_author(db)
    link(db, book, author)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute("DELETE FROM authors WHERE author_id = ?", (author,))


# 10
@pytest.mark.parametrize(
    "value", ["2026-02-30", "2026-13-01", "26-01-01", "2026/01/01", "2026-1-1"]
)
def test_invalid_dates_fail(db, value):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_book(db, acquired_on=value)


def test_valid_date_is_fine(db):
    add_book(db, acquired_on="2024-02-29")


# 11
def test_series_index_needs_a_series(db):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_book(db, series_index=2.0)


# 12
def test_unknown_format_fails(db):
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        add_book(db, format="scroll")


def test_unknown_role_fails(db):
    book, author = add_book(db), add_author(db)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        link(db, book, author, role="ghostwriter")


# 13
def test_updated_at_is_stamped_by_trigger(db):
    book = add_book(db)
    db.execute("UPDATE books SET updated_at = '2000-01-01T00:00:00Z' WHERE book_id = ?", (book,))
    db.execute("UPDATE books SET title = 'Changed' WHERE book_id = ?", (book,))
    stamped = db.execute("SELECT updated_at FROM books WHERE book_id = ?", (book,)).fetchone()[0]
    assert stamped > "2000-01-01T00:00:00Z"


def test_explicit_updated_at_is_kept(db):
    book = add_book(db)
    db.execute("UPDATE books SET updated_at = '2000-01-01T00:00:00Z' WHERE book_id = ?", (book,))
    assert db.execute("SELECT updated_at FROM books").fetchone()[0] == "2000-01-01T00:00:00Z"


# 14
def test_broken_migration_rolls_back(tmp_path):
    schema = tmp_path / "schema"
    schema.mkdir()
    (schema / "001_init.sql").write_text("CREATE TABLE t (x INTEGER) STRICT;", encoding="utf-8")
    (schema / "002_broken.sql").write_text(
        "CREATE TABLE half_done (x INTEGER) STRICT;\nCREATE TABLE bad (x BOGUS) STRICT;",
        encoding="utf-8",
    )
    db = tmp_path / "t.db"
    with pytest.raises(migrations.MigrationError, match="002_broken.sql"):
        migrations.migrate(db, schema)
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema")}
    assert "t" in names and "half_done" not in names
    conn.close()


# Beyond the table: other constraints worth pinning down.
def test_copies_must_be_positive(db):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_book(db, copies=0)


def test_subtitle_is_null_not_empty(db):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        add_book(db, subtitle="")


def test_loan_date_needs_a_borrower(db):
    book = add_book(db)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        db.execute(
            "INSERT INTO book_private (book_id, loaned_on) VALUES (?, '2026-01-01')", (book,)
        )


def test_active_books_hides_removed(db):
    add_book(db, "Kept")
    add_book(db, "Given away", removed_on="2026-03-01")
    assert [r[0] for r in db.execute("SELECT title FROM active_books")] == ["Kept"]
