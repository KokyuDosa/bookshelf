"""Genre suggestions from Open Library subjects, and scan --series."""

import builtins
from contextlib import closing

import pytest

from bookshelf import cli_books
from bookshelf.catalog import NewBook, add_book
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.genres import GenreMatcher, load_aliases, matcher_for
from bookshelf.openlibrary import Found, parse
from bookshelf.scan import Defaults, Session
from tests.test_scan import Script, typing

MINE = [
    "TTRPG",
    "Philosophy",
    "Politics",
    "Math",
    "Science Fiction",
    "Graphic Novel",
    "Biographies",
    "History",
]
KAIJU = {
    "9781974725984": Found(
        title="Kaiju No. 8, Vol. 1",
        authors=["Naoya Matsumoto"],
        subjects=["Manga", "Comics & graphic novels, manga, general"],
    ),
    "9781974727070": Found(title="Kaiju No. 8, Vol. 2", authors=["Naoya Matsumoto"]),
    "9781974728992": Found(title="Kaiju No. 8", subtitle="Vol. 3", authors=["Naoya Matsumoto"]),
    "9781974736201": Found(title="Kaiju No. 8", authors=["Naoya Matsumoto"]),  # no volume anywhere
    "9780061474095": Found(
        title="Anathem",
        subjects=["Science fiction", "Fiction", "Large type books", "Philosophy, Modern"],
    ),
}


def rows(conn, sql, params=()):
    return [tuple(r) for r in conn.execute(sql, params)]


# ---------------------------------------------------------------- matching


@pytest.mark.parametrize(
    ("subjects", "expected"),
    [
        (["Science fiction", "Fiction", "Large type books"], ["Science Fiction"]),
        (["Philosophy, Modern", "Philosophy -- History"], ["Philosophy"]),  # not History
        (["Mathematics", "Accessible book"], ["Math"]),  # alias
        (["Graphic novels"], ["Graphic Novel"]),  # plural
        (["Biography"], ["Biographies"]),  # -ies
        (["Politics and government", "United States"], ["Politics"]),
        (["Histories"], ["History"]),
        (["Manga"], []),  # not one of your genres
        (["Hist", "Physics"], []),
        ([], []),
    ],
)
def test_suggest_only_your_genres(subjects, expected):
    assert GenreMatcher(MINE, load_aliases()).suggest(subjects) == expected


def test_alias_to_a_genre_you_dont_use_is_ignored():
    m = GenreMatcher(["History"], {"Comics & graphic novels, manga, general": "Manga"})
    assert m.suggest(["Comics & graphic novels, manga, general"]) == []
    m = GenreMatcher(["Manga"], {"Comics & graphic novels, manga, general": "manga"})
    assert m.suggest(["Comics & graphic novels, manga, general"]) == ["Manga"]


def test_matcher_uses_tags_on_books_plus_extra(db, tmp_path):
    add_book(db, NewBook(title="A", tags=["Philosophy"]))
    db.execute("INSERT INTO tags (name, name_key) VALUES ('Orphan', 'orphan')")  # on no book
    m = matcher_for(db, ["Manga"], path=tmp_path / "none.toml")
    assert m.suggest(["Philosophy", "Orphan", "Manga"]) == ["Philosophy", "Manga"]


def test_parse_reads_subjects():
    assert parse(
        {
            "title": "T",
            "subjects": [{"name": "Science  fiction", "url": "u"}, "Fiction", {"url": "x"}, 3],
        }
    ).subjects == [
        "Science fiction",
        "Fiction",
    ]
    assert parse({"title": "T"}).subjects == []


# ---------------------------------------------------------------- scan


def session(db, *lines, series=None, tags=(), genres=MINE):
    script = Script(*lines)
    s = Session(
        db,
        KAIJU.get,
        script.read,
        script.say,
        defaults=Defaults(series=series, tags=list(tags)),
        bell=False,
        genres=GenreMatcher([*tags, *genres], load_aliases()) if genres is not None else None,
    )
    return s, script


def test_scan_adds_suggested_genres_and_says_so(db):
    s, script = session(db, "9780061474095")
    s.run()
    assert rows(db, "SELECT t.name FROM tags t JOIN book_tags USING (tag_id) ORDER BY 1") == [
        ("Philosophy",),
        ("Science Fiction",),
    ]
    assert "genres from Open Library: Science Fiction, Philosophy" in script.text


def test_scan_without_genres(db):
    s, script = session(db, "9780061474095", genres=None)
    s.run()
    assert rows(db, "SELECT count(*) FROM book_tags") == [(0,)]
    assert "genres from" not in script.text


def test_given_tag_isnt_repeated_as_a_suggestion(db):
    s, script = session(db, "9781974725984", tags=["Manga"], series="Kaiju No. 8")
    s.run()
    assert rows(db, "SELECT t.name FROM tags t JOIN book_tags USING (tag_id)") == [("Manga",)]
    assert "genres from" not in script.text


def test_scan_series_reads_volumes_from_titles(db):
    s, script = session(
        db, "9781974725984", "9781974727070", "9781974728992", series="Kaiju No. 8", tags=["Manga"]
    )
    s.run()
    assert rows(
        db,
        "SELECT b.title, s.name, b.series_index, b.subtitle FROM books b JOIN series s USING (series_id) ORDER BY b.book_id",
    ) == [
        ("Kaiju No. 8", "Kaiju No. 8", 1.0, None),
        ("Kaiju No. 8", "Kaiju No. 8", 2.0, None),
        ("Kaiju No. 8", "Kaiju No. 8", 3.0, None),  # the volume was in the subtitle
    ]
    assert "Added #2  Kaiju No. 8 — vol. 2 — Naoya Matsumoto" in script.text
    assert "Volume in" not in script.text  # never had to ask
    assert rows(db, "SELECT count(*) FROM review_flags") == [(0,)]  # volumes aren't duplicates


def test_scan_series_asks_and_suggests_the_next_volume(db):
    s, script = session(
        db,
        "9781974727070",  # vol. 2 from the title
        "9781974736201",
        "",  # no volume: Enter takes the suggestion, 3
        "9780061474095",
        "x",
        "4.5",  # a bad answer, then 4.5
        "u",  # undo 4.5: the next suggestion goes back to 4
        "9781974725984",  # vol. 1 from the title; no question
        series="Kaiju No. 8",
    )
    s.run()
    assert "  Volume in Kaiju No. 8 [3]: " in script.out
    assert "Type a number like 3 or 2.5" in script.text
    assert rows(db, "SELECT title, series_index FROM books ORDER BY book_id") == [
        ("Kaiju No. 8", 2.0),
        ("Kaiju No. 8", 3.0),
        ("Kaiju No. 8", 1.0),
    ]
    assert s.last_volume == 1.0


def test_scan_series_dash_means_no_volume_and_first_has_no_suggestion(db):
    s, script = session(db, "9781974736201", "-", series="Kaiju No. 8")
    s.run()
    assert "  Volume in Kaiju No. 8 (Enter = none): " in script.out
    assert rows(db, "SELECT series_index FROM books") == [(None,)]


def test_scan_series_on_typed_titles_and_placeholders(db):
    s, _ = session(
        db,
        "9780786928866",
        "Kaiju No. 8, Vol. 9",
        "",
        "9780786928873",
        "",
        "10",
        series="Kaiju No. 8",
    )
    s.run()
    assert rows(db, "SELECT title, series_index, is_public FROM books ORDER BY book_id") == [
        ("Kaiju No. 8", 9.0, 1),
        ("ISBN 9780786928873", 10.0, 0),
    ]


def test_scan_command_series_and_no_genres(db_path, monkeypatch, capsys):
    class FakeOL:
        def __init__(self, conn):
            pass

        def lookup(self, isbn):
            return KAIJU.get(isbn)

    monkeypatch.setattr(cli_books, "OpenLibrary", FakeOL)
    with closing(connect(db_path)) as conn, conn:
        add_book(conn, NewBook(title="Old", tags=["Science Fiction"]))
    monkeypatch.setattr(builtins, "input", typing("9781974725984", "9780061474095", "5"))
    assert (
        main(["--db", str(db_path), "scan", "--series", "Kaiju No. 8", "--tag", "Manga", "--quiet"])
        == 0
    )
    out = capsys.readouterr().out
    assert "genres from Open Library: Science Fiction" in out
    monkeypatch.setattr(builtins, "input", typing("9781974727070"))
    assert main(["--db", str(db_path), "scan", "--no-genres", "--quiet"]) == 0
    with closing(connect(db_path)) as conn:
        assert rows(conn, "SELECT b.title, b.series_index FROM books b ORDER BY book_id") == [
            ("Old", None),
            ("Kaiju No. 8", 1.0),
            ("Anathem", 5.0),
            ("Kaiju No. 8, Vol. 2", None),  # no --series: the title is kept as Open Library has it
        ]


# ---------------------------------------------------------------- add


@pytest.fixture
def fake_ol(monkeypatch):
    class FakeOL:
        def __init__(self, conn):
            pass

        def lookup(self, isbn):
            return KAIJU.get(isbn)

    monkeypatch.setattr(cli_books, "OpenLibrary", FakeOL)


def test_add_suggests_genres(db_path, fake_ol, capsys):
    with closing(connect(db_path)) as conn, conn:
        add_book(conn, NewBook(title="Old", tags=["Science Fiction", "Philosophy"]))
    assert main(["--db", str(db_path), "add", "9780061474095", "-y"]) == 0
    assert (
        "Genres from Open Library: Science Fiction, Philosophy (--no-genres to skip)"
        in capsys.readouterr().out
    )
    assert (
        main(["--db", str(db_path), "add", "9781974725984", "--no-genres", "--tag", "Manga", "-y"])
        == 0
    )
    with closing(connect(db_path)) as conn:
        assert rows(
            conn,
            "SELECT b.title, group_concat(t.name, ', ') FROM books b JOIN book_tags USING (book_id) "
            "JOIN tags t USING (tag_id) WHERE b.book_id > 1 GROUP BY b.book_id ORDER BY b.book_id",
        ) == [("Anathem", "Science Fiction, Philosophy"), ("Kaiju No. 8, Vol. 1", "Manga")]


def test_add_series_takes_volume_from_title(db_path, fake_ol):
    assert (
        main(["--db", str(db_path), "add", "9781974727070", "--series", "Kaiju No. 8", "-y"]) == 0
    )
    assert (
        main(
            [
                "--db",
                str(db_path),
                "add",
                "9781974725984",
                "--series",
                "Kaiju No. 8",
                "--volume",
                "7",
                "-y",
            ]
        )
        == 0
    )
    with closing(connect(db_path)) as conn:
        assert rows(conn, "SELECT title, series_index FROM books ORDER BY book_id") == [
            ("Kaiju No. 8", 2.0),
            ("Kaiju No. 8, Vol. 1", 7.0),  # --volume given: the title is left alone
        ]
