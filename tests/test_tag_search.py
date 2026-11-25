"""bookshelf search --tag and bookshelf tags."""

from contextlib import closing

import pytest

from bookshelf.catalog import NewBook, add_book
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.search import browse_order, genre_counts, resolve_genres, with_genres


def run(db_path, *args):
    return main(["--db", str(db_path), *args])


@pytest.fixture
def shelf(db_path):
    with closing(connect(db_path)) as conn, conn:
        for title, tags, extra in [
            ("Being and Event", ["Philosophy"], {}),
            ("Anarchy Works", ["Philosophy", "Politics"], {}),
            ("Calculus", ["Math"], {}),
            ("Remission", ["Graphic Novel"], {"series": "Prophet", "series_index": 1}),
            ("Brothers", ["Graphic Novel"], {"series": "Prophet", "series_index": 2}),
            ("Secret Diary", ["Philosophy"], {"is_public": False}),  # hidden: still yours
        ]:
            add_book(conn, NewBook(title=title, tags=tags, **extra))
        gone = add_book(conn, NewBook(title="Sold Off", tags=["Philosophy"]))
        conn.execute("UPDATE books SET removed_on = '2026-01-01' WHERE book_id = ?", (gone,))
    return db_path


def test_tag_alone_lists_the_genre_a_to_z(shelf, capsys):
    assert run(shelf, "search", "--tag", "philosophy") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "In Philosophy (3):"
    assert out.index("Anarchy Works") < out.index("Being and Event") < out.index("Secret Diary")
    assert "Sold Off" not in out


def test_tag_and_words_combine(shelf, capsys):
    assert run(shelf, "search", "anarchy", "--tag", "Philosophy") == 0
    assert "Anarchy Works" in capsys.readouterr().out
    assert run(shelf, "search", "calculus", "--tag", "Philosophy") == 1
    assert "Nothing in Philosophy matches." in capsys.readouterr().out


def test_several_tags_must_all_match(shelf, capsys):
    assert run(shelf, "search", "--tag", "philosophy", "--tag", "politics") == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "In Philosophy + Politics:",
        "      2  Anarchy Works",
    ]


def test_plural_and_case_dont_matter_and_series_stay_in_order(shelf, capsys):
    assert run(shelf, "search", "--tag", "GRAPHIC NOVELS") == 0
    out = capsys.readouterr().out
    assert out.index("Remission") < out.index("Brothers")  # vol. 1 before vol. 2


def test_unknown_tag_suggests_close_ones(shelf, capsys):
    assert run(shelf, "search", "--tag", "phil") == 1
    err = capsys.readouterr().err
    assert "No genre called 'phil'. Did you mean: Philosophy?" in err
    assert "'bookshelf tags' lists your genres." in err


def test_needs_words_or_a_tag(shelf, capsys):
    assert run(shelf, "search") == 1
    assert "bookshelf search --tag Philosophy" in capsys.readouterr().err


def test_limit_hint_names_the_number(shelf, capsys):
    assert run(shelf, "search", "--tag", "philosophy", "--limit", "1") == 0
    assert "… and 2 more (use --limit 3)" in capsys.readouterr().out


def test_tags_command(shelf, capsys):
    assert run(shelf, "tags") == 0
    assert capsys.readouterr().out.splitlines() == [
        "4 genres:",
        "  3  Philosophy",
        "  2  Graphic Novel",
        "  1  Math",
        "  1  Politics",
    ]
    assert run(shelf, "tags", "--by-name") == 0
    assert capsys.readouterr().out.splitlines()[1:3] == ["  2  Graphic Novel", "  1  Math"]


def test_tags_command_empty(db_path, capsys):
    assert run(db_path, "tags") == 0
    assert "No genres yet" in capsys.readouterr().out


def test_helpers():
    books = [
        {"id": 1, "title": "B", "key": "b", "tags": ["Math", "Biographies"]},
        {"id": 2, "title": "A", "key": "a", "tags": ["Math"]},
        {"id": 3, "title": "Z", "key": "z", "line": "Alpha", "tags": []},
    ]
    assert genre_counts(books) == [("Math", 2), ("Biographies", 1)]
    assert resolve_genres(books, ["math", "biography", "maths", "xyz"]) == (
        ["Math", "Biographies"],
        {"xyz": []},
    )
    assert [b["id"] for b in with_genres(books, ["Math", "Biographies"])] == [1]
    assert [b["id"] for b in browse_order(books)] == [2, 1, 3]  # no line first, like the website
