"""The six M1 refresher queries, run against the seed data."""

import pytest

from bookshelf.paths import PROJECT_ROOT

QUERIES = PROJECT_ROOT / "queries"


def run(db, name, **params):
    return [tuple(r) for r in db.execute((QUERIES / f"{name}.sql").read_text("utf-8"), params)]


def test_01_books_by_author_series_first(seeded):
    rows = run(seeded, "01_books_by_author", author_key="tolkien j r r")
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("The Fellowship of the Ring", "The Lord of the Rings", 1.0),
        ("The Two Towers", "The Lord of the Rings", 2.0),
        ("The Hobbit", None, None),
    ]


def test_02_formats_include_empty_ones(seeded):
    rows = {r[0]: (r[2], r[3]) for r in run(seeded, "02_books_per_format")}
    assert rows["hardcover"] == (3, 4)  # The Hobbit counts as one edition, two copies
    assert rows["audiobook"] == (0, 0)
    assert rows["mass_market"] == (2, 2)  # Dune is soft-deleted, so not counted
    assert len(rows) == seeded.execute("SELECT count(*) FROM formats").fetchone()[0]


@pytest.mark.parametrize(
    ("min_books", "expected"),
    [(1, [("J.R.R. Tolkien", 3), ("Ursula K. Le Guin", 2)]), (2, [("J.R.R. Tolkien", 3)])],
)
def test_03_prolific_authors(seeded, min_books, expected):
    assert run(seeded, "03_prolific_authors", min_books=min_books) == expected


def test_04_books_needing_attention(seeded):
    titles = {r[1] for r in run(seeded, "04_books_needing_attention")}
    assert titles == {"Gods of Risk", "The Time Machine", "The Republic"}


def test_04_finds_a_book_with_no_credits(seeded):
    seeded.execute(
        "INSERT INTO books (title, sort_title, title_key, natural_key, isbn13) "
        "VALUES ('Orphan', 'Orphan', 'orphan', 'orphan||', '9780306406157')"
    )
    rows = {r[1]: (r[2], r[3]) for r in run(seeded, "04_books_needing_attention")}
    assert rows["Orphan"] == (0, 1)


def test_05_credits_in_order_with_roles(seeded):
    rows = {r[1]: r[2] for r in run(seeded, "05_books_with_credits")}
    assert rows["Good Omens"] == "Terry Pratchett; Neil Gaiman"
    assert (
        rows["One Hundred Years of Solitude"]
        == "Gabriel García Márquez; Gregory Rabassa (translator)"
    )
    assert "Dune" not in rows


def test_06_plan_uses_indexes_only(seeded):
    details = [r[3] for r in run(seeded, "06_plan_books_by_author", author_key="tolkien j r r")]
    assert not [d for d in details if d.startswith("SCAN")], details
    assert any("book_authors_author" in d for d in details)
