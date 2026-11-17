import sqlite3

import pytest

from bookshelf.catalog import Credit, NewBook, add_book
from bookshelf.isbn import InvalidISBN
from bookshelf.seed import SEED_BOOKS, seed


def test_seed_loads_every_book(seeded):
    assert seeded.execute("SELECT count(*) FROM books").fetchone()[0] == len(SEED_BOOKS)
    assert seeded.execute("PRAGMA foreign_key_check").fetchall() == []
    assert seeded.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_seed_refuses_a_database_with_books(seeded):
    with pytest.raises(RuntimeError):
        seed(seeded)


def test_name_variants_become_one_author(seeded):
    rows = seeded.execute(
        "SELECT count(*) FROM authors WHERE match_key = 'tolkien j r r'"
    ).fetchone()
    assert rows[0] == 1
    credited = seeded.execute(
        "SELECT count(*) FROM book_authors JOIN authors USING (author_id) WHERE match_key = 'tolkien j r r'"
    ).fetchone()
    assert credited[0] == 3


def test_keys_are_computed(db):
    book_id = add_book(
        db, NewBook("The Hobbit", [Credit("J.R.R. Tolkien")], isbn="0-306-40615-2", pub_year=1937)
    )
    row = db.execute("SELECT * FROM books WHERE book_id = ?", (book_id,)).fetchone()
    assert row["sort_title"] == "Hobbit, The"
    assert row["title_key"] == "hobbit"
    assert row["natural_key"] == "hobbit|tolkien j r r|1937"
    assert row["isbn13"] == "9780306406157"


def test_natural_key_uses_first_author_not_translator(db):
    book = NewBook(
        "Solitude", [Credit("Gregory Rabassa", "translator"), Credit("García Márquez, Gabriel")]
    )
    book_id = add_book(db, book)
    key = db.execute("SELECT natural_key FROM books WHERE book_id = ?", (book_id,)).fetchone()[0]
    assert key == "solitude|garcia marquez gabriel|"


def test_anthology_falls_back_to_first_editor(db):
    book_id = add_book(db, NewBook("Anthology", [Credit("Ann VanderMeer", "editor")]))
    key = db.execute("SELECT natural_key FROM books WHERE book_id = ?", (book_id,)).fetchone()[0]
    assert key == "anthology|vandermeer ann|"


def test_bad_isbn_is_rejected_before_insert(db):
    with pytest.raises(InvalidISBN):
        add_book(db, NewBook("X", isbn="0-306-40615-3"))
    assert db.execute("SELECT count(*) FROM books").fetchone()[0] == 0


def test_same_isbn_twice_is_refused(db):
    add_book(db, NewBook("First", isbn="0306406152"))
    with pytest.raises(sqlite3.IntegrityError):
        add_book(db, NewBook("Second", isbn="978-0-306-40615-7"))


def test_private_fields_go_to_side_table(seeded):
    assert seeded.execute("SELECT count(*) FROM book_private").fetchone()[0] == 2
    cols = [r[1] for r in seeded.execute("PRAGMA table_info(books)")]
    assert not {"purchase_price_cents", "notes", "loaned_to"} & set(cols)


def test_series_is_part_of_the_natural_key(db):
    a = add_book(db, NewBook("Core Rulebook", series="Ashen Stars"))
    b = add_book(db, NewBook("Core Rulebook", series="Cyberpunk Red"))
    keys = [
        r[0] for r in db.execute("SELECT natural_key FROM books WHERE book_id IN (?, ?)", (a, b))
    ]
    assert keys == ["ashen stars core rulebook||", "cyberpunk red core rulebook||"]


def test_update_overwrite_replaces_supplied_values_only(db):
    from bookshelf.catalog import update_book

    book_id = add_book(db, NewBook("Old", [Credit("Ben Robbins")], pub_year=2010, edition="1st"))
    update_book(db, book_id, NewBook("New", [Credit("Kenneth Hite")], edition="2nd"), "overwrite")
    row = db.execute("SELECT * FROM books WHERE book_id = ?", (book_id,)).fetchone()
    assert (row["title"], row["edition"], row["pub_year"]) == ("New", "2nd", 2010)
    assert row["natural_key"] == "new|hite kenneth|2010"
    names = [
        r[0]
        for r in db.execute(
            "SELECT a.display_name FROM book_authors JOIN authors a USING (author_id)"
        )
    ]
    assert names == ["Kenneth Hite"]


def test_update_fill_never_replaces(db):
    from bookshelf.catalog import update_book

    book_id = add_book(
        db, NewBook("Mine", [Credit("Ben Robbins")], copies=3, estimated_value_cents=500)
    )
    update_book(
        db,
        book_id,
        NewBook(
            "Theirs", [Credit("Kenneth Hite")], publisher="Lame Mage", estimated_value_cents=900
        ),
        "fill",
    )
    row = db.execute(
        "SELECT b.title, b.copies, b.publisher, p.estimated_value_cents FROM books b "
        "JOIN book_private p USING (book_id) WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    assert tuple(row) == ("Mine", 3, "Lame Mage", 500)
    assert db.execute("SELECT count(*) FROM book_authors").fetchone()[0] == 1
