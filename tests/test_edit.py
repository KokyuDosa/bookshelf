"""bookshelf show and bookshelf edit."""

import json
from contextlib import closing

import pytest

from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.importers.mapping import Mapping
from bookshelf.importers.pipeline import import_file
from bookshelf.paths import PROJECT_ROOT
from tests.test_import import BOOKS, write_export


@pytest.fixture
def lib(db_path, seeded):
    seeded.commit()
    return db_path


def run(db_path, *args):
    return main(["--db", str(db_path), *args])


def book_id(db_path, title):
    with closing(connect(db_path)) as conn:
        return conn.execute("SELECT book_id FROM books WHERE title = ?", (title,)).fetchone()[0]


def show_json(db_path, ref, capsys):
    capsys.readouterr()
    assert run(db_path, "show", ref, "--json") == 0
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- show


@pytest.mark.parametrize(
    "ref",
    ["the hobbit", "1", "0-00-000001-9", "9780000000019"],  # words, number, ISBN-10, ISBN-13
)
def test_show_finds_by_words_number_or_isbn(lib, capsys, ref):
    assert run(lib, "show", *ref.split()) == 0
    assert capsys.readouterr().out.startswith("Book 1: The Hobbit")


def test_show_includes_private_values_and_record(lib, capsys):
    d = show_json(lib, "the hobbit", capsys)
    assert d["private"] == {"price_cents": 1899, "value_cents": None, "notes": None,
                            "loaned_to": "Sam", "loaned_on": "2026-10-01"}  # fmt: skip
    assert d["shelf"] == "Living room A2" and d["copies"] == 2 and d["isbn10"] == "0000000019"
    assert d["keys"]["natural_key"] == "hobbit|tolkien j r r|1937"
    run(lib, "show", "1")
    text = capsys.readouterr().out
    assert "price paid       $18.99" in text and "Private (never published)" in text


def test_show_ambiguous_lists_numbers(lib, capsys):
    assert run(lib, "show", "le", "guin") == 1
    err = capsys.readouterr().err
    assert (
        "2 books match" in err
        and "A Wizard of Earthsea" in err
        and "The Left Hand of Darkness" in err
    )


def test_show_removed_book_by_number(lib, capsys):
    d = show_json(lib, str(book_id(lib, "Dune")), capsys)
    assert d["removed"] == "2026-03-01"


@pytest.mark.parametrize(
    ("ref", "message"), [("999", "No book matches"), ("0-306-40615-3", "isn't a valid ISBN")]
)
def test_show_nothing(lib, capsys, ref, message):
    assert run(lib, "show", ref) == 1
    assert message in capsys.readouterr().err


def test_search_prints_numbers(lib, capsys):
    run(lib, "search", "hobbit")
    assert "    1  The Hobbit" in capsys.readouterr().out


# ---------------------------------------------------------------- edit


def test_clear_and_set_isbn(lib, capsys):
    assert run(lib, "edit", "1", "--clear", "isbn") == 0
    assert "isbn: 9780000000019  ->  (empty)" in capsys.readouterr().out
    assert show_json(lib, "1", capsys)["isbn13"] is None
    assert run(lib, "edit", "1", "--isbn", "0-306-40615-2") == 0
    assert show_json(lib, "1", capsys)["isbn13"] == "9780306406157"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--isbn", "978-0-00-000101-6"], "already has ISBN"),
        (["--isbn", "0-306-40615-3"], "isn't a valid ISBN"),
        (["--title", "  "], "at least one letter"),
        (["--volume", "2"], "needs a series"),
        (["--volume", "2", "--clear", "series"], "needs a series"),
        (["--acquired", "2026-02-30"], "must be a date"),
        (["--loaned-on", "2026-01-01", "--clear", "loan"], "needs a borrower"),
        (["--format", "scroll"], "use one of"),
        (["--year", "99"], "CHECK constraint failed"),
        (["--copies", "0"], "CHECK constraint failed"),
        (["--value", "lots"], "not an amount"),
        (["--remove", "--restore"], "can't be used together"),
        ([], "Nothing to change"),
    ],
)
def test_edit_refuses_and_changes_nothing(lib, capsys, args, message):
    before = show_json(lib, "1", capsys)
    assert run(lib, "edit", "1", *args) == 1
    assert message in capsys.readouterr().err
    assert show_json(lib, "1", capsys) == before


def test_edit_title_refreshes_keys(lib, capsys):
    run(lib, "edit", "1", "--title", "The Hobbit, or There and Back Again", "--year", "1938")
    d = show_json(lib, "1", capsys)
    assert d["keys"]["sort_title"] == "Hobbit, or There and Back Again, The"
    assert d["keys"]["natural_key"] == "hobbit or there and back again|tolkien j r r|1938"


def test_series_volume_and_clearing_series(lib, capsys):
    run(lib, "edit", "1", "--series", "Middle-earth", "--volume", "0.5")
    d = show_json(lib, "1", capsys)
    assert (d["series"], d["volume"]) == ("Middle-earth", 0.5)
    assert (
        d["keys"]["natural_key"] == "middle earth vol 0 5 the hobbit|tolkien j r r|1937"
    )  # series + title
    run(lib, "edit", "1", "--clear", "series")
    d = show_json(lib, "1", capsys)
    assert (d["series"], d["volume"]) == (None, None)
    run(
        lib, "edit", "1", "--clear", "series", "--series", "Tolkien", "--volume", "1"
    )  # clear, then set
    d = show_json(lib, "1", capsys)
    assert (d["series"], d["volume"]) == ("Tolkien", 1.0)


def test_credits_replace_in_typed_order(lib, capsys):
    hundred = str(book_id(lib, "One Hundred Years of Solitude"))
    run(
        lib,
        "edit",
        hundred,
        "--translator",
        "Edith Grossman",
        "--author",
        "García Márquez, Gabriel",
    )
    credits = [(c["name"], c["role"]) for c in show_json(lib, hundred, capsys)["credits"]]
    assert credits == [("Edith Grossman", "translator"), ("Gabriel García Márquez", "author")]
    run(lib, "edit", hundred, "--clear", "authors")
    assert show_json(lib, hundred, capsys)["credits"] == []


def test_tags_add_remove_clear(lib, capsys):
    run(lib, "edit", "1", "--add-tag", "Classics", "--remove-tag", "FANTASY")
    assert show_json(lib, "1", capsys)["tags"] == ["Classics"]
    run(lib, "edit", "1", "--clear", "tags")
    assert show_json(lib, "1", capsys)["tags"] == []


def test_private_fields(lib, capsys):
    run(
        lib,
        "edit",
        "1",
        "--value",
        "$1,250.00",
        "--notes",
        "Signed",
        "--clear",
        "loan",
        "--clear",
        "price",
    )
    p = show_json(lib, "1", capsys)["private"]
    assert p == {
        "price_cents": None,
        "value_cents": 125000,
        "notes": "Signed",
        "loaned_to": None,
        "loaned_on": None,
    }
    run(lib, "edit", "2", "--loaned-to", "Kim", "--loaned-on", "2026-11-01")  # no private row yet
    assert show_json(lib, "2", capsys)["private"]["loaned_to"] == "Kim"


def test_remove_and_restore(lib, capsys):
    run(lib, "edit", "1", "--remove", "2026-11-17")
    assert show_json(lib, "1", capsys)["removed"] == "2026-11-17"
    assert run(lib, "search", "hobbit") == 1  # gone from searches and the website
    run(lib, "edit", "1", "--restore")
    assert show_json(lib, "1", capsys)["removed"] is None


def test_no_change_is_reported(lib, capsys):
    assert run(lib, "edit", "1", "--copies", "2") == 0
    assert "No change" in capsys.readouterr().out


def test_edits_survive_reimporting_an_unchanged_export(db_path, tmp_path, capsys):
    """SQLite is the master: re-importing the same MyStuff2 file must not undo your edits."""
    mapping = Mapping.load(PROJECT_ROOT / "config" / "mappings" / "mystuff2.toml")
    export = write_export(tmp_path / "Books.csv", BOOKS)
    import_file(db_path, export, mapping)
    feng = str(book_id(db_path, "Feng Shui"))
    run(db_path, "edit", feng, "--isbn", "9780306406157", "--title", "Feng Shui (1st edition)")
    report = import_file(db_path, export, mapping)
    assert report.unchanged == 3 and report.updated == 0
    d = show_json(db_path, feng, capsys)
    assert (d["title"], d["isbn13"]) == ("Feng Shui (1st edition)", "9780306406157")
