"""A set's contents: slipcase sets with one ISBN and several pieces (migration 004)."""

import json
from contextlib import closing

import pytest

from bookshelf.catalog import NewBook, Part, add_book, parse_part, read_parts
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.export import books_csv, books_json, public_books
from bookshelf.search import describe, search

MALLEUS_ISBN = "9781568823348"


def run(db_path, *args):
    return main(["--db", str(db_path), *args])


def parts(db_path, book_id=1):
    with closing(connect(db_path)) as conn:
        return [(p.kind, p.label, p.have) for p in read_parts(conn, book_id)]


@pytest.fixture
def malleus(db_path):
    assert (
        run(
            db_path,
            "add",
            MALLEUS_ISBN,
            "--title",
            "Malleus Monstrorum",
            "--line",
            "Call of Cthulhu",
            "--format",
            "box set",
            "--part",
            "Vol. 1: Monsters of the Mythos",
            "--part",
            "Vol. 2: Deities of the Mythos",
            "--part",
            "Slipcase",
            "--offline",
            "-y",
        )
        == 0
    )
    return db_path


@pytest.mark.parametrize(
    ("text", "kind", "label"),
    [
        ("Vol. 1: Monsters of the Mythos", "volume", "Vol. 1: Monsters of the Mythos"),
        ("Volume II", "volume", "Volume II"),
        ("v2", "volume", "v2"),
        ("Slipcase", "slipcase", "Slipcase"),
        ("Slip case", "slipcase", "Slip case"),
        ("handouts: Keeper's folder", "handouts", "Keeper's folder"),  # kind given before ':'
        ("Investigator Handouts", "handouts", "Investigator Handouts"),
        ("Keeper Screen", "screen", "Keeper Screen"),
        ("Map of Arkham", "map", "Map of Arkham"),
        ("Poster", "other", "Poster"),
        ("Notes: on the slipcase", "slipcase", "Notes: on the slipcase"),  # 'Notes' isn't a kind
    ],
)
def test_parse_part(text, kind, label):
    assert parse_part(text) == Part(label, kind)


def test_parse_part_needs_a_name():
    with pytest.raises(ValueError):
        parse_part(" - ")


def test_add_a_set_with_its_parts(malleus):
    assert parts(malleus) == [
        ("volume", "Vol. 1: Monsters of the Mythos", True),
        ("volume", "Vol. 2: Deities of the Mythos", True),
        ("slipcase", "Slipcase", True),
    ]


def test_show_lists_numbered_parts(malleus, capsys):
    capsys.readouterr()
    assert run(malleus, "show", "1") == 0
    out = capsys.readouterr().out
    assert "  2  volume    Vol. 2: Deities of the Mythos" in out
    assert "  3  slipcase  Slipcase" in out


def test_edit_parts(malleus, capsys):
    assert run(malleus, "edit", "1", "--add-part", "handouts: Keeper folder", "-y") == 0
    assert run(malleus, "edit", "1", "--missing-part", "4", "-y") == 0
    capsys.readouterr()
    assert run(malleus, "show", "1") == 0
    assert "Keeper folder   [missing]" in capsys.readouterr().out
    assert run(malleus, "edit", "1", "--found-part", "4", "--remove-part", "3", "-y") == 0
    assert parts(malleus) == [
        ("volume", "Vol. 1: Monsters of the Mythos", True),
        ("volume", "Vol. 2: Deities of the Mythos", True),
        ("handouts", "Keeper folder", True),  # renumbered: now part 3
    ]
    assert run(malleus, "edit", "1", "--clear", "parts", "-y") == 0
    assert parts(malleus) == []


def test_edit_shows_part_changes(malleus, capsys):
    capsys.readouterr()
    run(malleus, "edit", "1", "--missing-part", "3", "-y")
    assert "Slipcase (missing)" in capsys.readouterr().out


def test_bad_part_number_changes_nothing(malleus, capsys):
    assert run(malleus, "edit", "1", "--remove-part", "9", "--line", "X", "-y") == 1
    assert "numbered 1 to 3" in capsys.readouterr().err
    assert len(parts(malleus)) == 3
    assert run(malleus, "edit", "1", "--missing-part", "1", "--found-part", "1", "-y") == 1


def test_one_isbn_finds_the_set_and_its_volumes_are_searchable(malleus):
    with closing(connect(malleus)) as conn:
        books = public_books(conn)
    assert [b["title"] for b in search(books, MALLEUS_ISBN).books] == ["Malleus Monstrorum"]
    assert [b["id"] for b in search(books, "deities of the mythos").books] == [1]
    assert describe(books[0]).endswith(
        "contains Vol. 1: Monsters of the Mythos + Vol. 2: Deities of the Mythos + Slipcase"
    )


def test_missing_flag_is_never_published(malleus):
    run(malleus, "edit", "1", "--missing-part", "3", "-y")
    with closing(connect(malleus)) as conn:
        published = books_json(conn)
        csv_text = books_csv(conn)
    book = json.loads(published)["books"][0]
    assert book["contents"] == [
        "Vol. 1: Monsters of the Mythos",
        "Vol. 2: Deities of the Mythos",
        "Slipcase",
    ]
    assert "missing" not in published.lower() and "have" not in book
    assert csv_text.splitlines()[0].endswith(",Contents")
    assert "Deities of the Mythos; Slipcase" in csv_text


def test_parts_are_deleted_with_the_book(db):
    book_id = add_book(db, NewBook(title="Set", parts=[Part("A", "volume")]))
    db.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
    assert db.execute("SELECT count(*) FROM book_parts").fetchone()[0] == 0


def test_unknown_kind_is_refused_by_the_database(db):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        add_book(db, NewBook(title="Set", parts=[Part("A", "gizmo")]))


def test_edit_many_cannot_change_parts(db_path):
    with pytest.raises(SystemExit):
        run(db_path, "edit-many", "--all", "--add-part", "Slipcase")
