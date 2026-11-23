"""Product lines (migration 003), the cells hash on re-import, and edit-many."""

import shutil
import sqlite3
from contextlib import closing

import pytest

from bookshelf import migrations
from bookshelf.catalog import NewBook, add_book, book_natural_key
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.editing import parse_ids, trim_prefix
from bookshelf.export import books_csv, public_books
from bookshelf.importers.mapping import Mapping
from bookshelf.importers.pipeline import HASH_VERSION, import_file
from bookshelf.paths import PROJECT_ROOT, SCHEMA_DIR
from bookshelf.search import describe
from tests.test_import import BOOKS, write_export

MAPPING = Mapping.load(PROJECT_ROOT / "config" / "mappings" / "mystuff2.toml")


def run(db_path, *args):
    return main(["--db", str(db_path), *args])


def rows(db_path, sql, params=()):
    with closing(connect(db_path)) as conn:
        return [tuple(r) for r in conn.execute(sql, params)]


def lines_of(db_path):
    return dict(
        rows(
            db_path,
            "SELECT b.title, pl.name FROM books b LEFT JOIN product_lines pl USING (line_id)",
        )
    )


# ---------------------------------------------------------------- migration 003


def test_migration_moves_unnumbered_series_into_lines(tmp_path):
    old_schema = tmp_path / "schema"
    old_schema.mkdir()
    for name in ("001_init.sql", "002_api_cache.sql"):
        shutil.copy(SCHEMA_DIR / name, old_schema)
    db = tmp_path / "books.db"
    migrations.migrate(db, old_schema)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.executemany(
            "INSERT INTO series (series_id, name, name_key) VALUES (?, ?, ?)",
            [(1, "DND 3.5", "dnd 3 5"), (2, "Happiness", "happiness")],
        )
        conn.executemany(
            "INSERT INTO books (title, sort_title, title_key, natural_key, series_id, series_index)"
            " VALUES (?, '', '', '', ?, ?)",
            [
                ("Monster Manual", 1, None),
                ("Player's Handbook", 1, None),
                ("Happiness", 2, 1.0),
                ("Happiness extra", 2, None),  # unnumbered, but its series has numbers
                ("Loose", None, None),
            ],
        )

    assert run(db, "migrate") == 0
    got = rows(
        db,
        "SELECT b.title, pl.name, s.name, b.series_index FROM books b "
        "LEFT JOIN product_lines pl USING (line_id) LEFT JOIN series s USING (series_id) "
        "ORDER BY b.book_id",
    )
    assert got == [
        ("Monster Manual", "DND 3.5", None, None),
        ("Player's Handbook", "DND 3.5", None, None),
        ("Happiness", None, "Happiness", 1.0),
        ("Happiness extra", None, "Happiness", None),
        ("Loose", None, None, None),
    ]
    assert rows(db, "SELECT name FROM series") == [("Happiness",)]
    assert rows(db, "SELECT name, name_key FROM product_lines") == [("DND 3.5", "dnd 3 5")]
    assert rows(db, "PRAGMA foreign_key_check") == []


# ---------------------------------------------------------------- the line field


def test_import_puts_the_title_prefix_in_the_line(db_path, tmp_path):
    import_file(db_path, write_export(tmp_path / "b.csv", BOOKS), MAPPING)
    assert lines_of(db_path)["Player's Handbook"] == "DND 3.5"
    assert rows(db_path, "SELECT count(*) FROM series") == [(0,)]


def test_line_is_part_of_identity():
    dnd = book_natural_key("Monster Manual", "DND 3.5", None, None, None, None)
    pf = book_natural_key("Monster Manual", "Pathfinder", None, None, None, None)
    bare = book_natural_key("Monster Manual", None, None, None, None, None)
    assert len({dnd, pf, bare}) == 3


def test_line_in_search_export_and_display(db):
    add_book(db, NewBook(title="Bestiary", line="Pathfinder"))
    add_book(
        db, NewBook(title="Burnt Offerings", line="Pathfinder", series="Runelords", series_index=1)
    )
    add_book(db, NewBook(title="Anathem"))
    books = {b["title"]: b for b in public_books(db)}
    assert books["Bestiary"]["line"] == "Pathfinder"
    assert "pathfinder" in books["Bestiary"]["key"].split()
    assert "line" not in books["Anathem"]
    assert (
        describe(books["Burnt Offerings"]) == "Burnt Offerings  —  Pathfinder  —  Runelords, vol. 1"
    )
    csv_rows = books_csv(db).splitlines()
    assert csv_rows[0].startswith("Line,Title,")
    # sorted by line: books without one ("") first, then the Pathfinder books, loose before series
    assert [r.split(",")[1] for r in csv_rows[1:]] == ["Anathem", "Bestiary", "Burnt Offerings"]


def test_add_and_edit_line(db_path, capsys):
    assert (
        run(db_path, "add", "--title", "Monster Manual", "--line", "DND 3.5", "--offline", "-y")
        == 0
    )
    assert lines_of(db_path)["Monster Manual"] == "DND 3.5"
    assert run(db_path, "edit", "1", "--line", "D&D 3.5", "-y") == 0
    assert lines_of(db_path)["Monster Manual"] == "D&D 3.5"
    assert run(db_path, "edit", "1", "--clear", "line", "-y") == 0
    assert lines_of(db_path)["Monster Manual"] is None
    capsys.readouterr()
    assert run(db_path, "show", "1") == 0
    assert "  line             -" in capsys.readouterr().out


def test_same_line_name_is_one_line(db_path):
    run(db_path, "add", "--title", "A", "--line", "DND 3.5", "--offline", "-y")
    run(db_path, "add", "--title", "B", "--line", "dnd  3.5", "--offline", "-y")
    assert rows(db_path, "SELECT count(*) FROM product_lines") == [(1,)]


# ---------------------------------------------------------------- re-import safety


@pytest.fixture
def imported(db_path, tmp_path):
    export = write_export(tmp_path / "Books.csv", BOOKS)
    import_file(db_path, export, MAPPING)
    return db_path, export


def test_legacy_hash_with_same_row_counts_as_unchanged(imported):
    db_path, export = imported
    with closing(connect(db_path)) as conn, conn:
        conn.execute("UPDATE source_records SET row_hash = 'old-style-hash'")
        conn.execute("UPDATE books SET title = 'My Fix' WHERE title = 'Feng Shui'")
    report = import_file(db_path, export, MAPPING)
    assert (report.updated, report.unchanged) == (0, 3)
    assert "My Fix" in lines_of(db_path)
    assert all(
        h.startswith(HASH_VERSION) for (h,) in rows(db_path, "SELECT row_hash FROM source_records")
    )


def test_legacy_hash_with_changed_row_updates(imported, tmp_path):
    db_path, _ = imported
    with closing(connect(db_path)) as conn, conn:
        conn.execute("UPDATE source_records SET row_hash = 'old-style-hash'")
    edited = [dict(b) for b in BOOKS]
    edited[1]["title"] = "Feng Shui 2"
    report = import_file(db_path, write_export(tmp_path / "b2.csv", edited), MAPPING)
    assert (report.updated, report.unchanged) == (1, 2)


def test_trim_title_survives_reimport_until_remap(imported):
    db_path, export = imported
    assert (
        run(
            db_path,
            "edit-many",
            "--title-has",
            "call of cthulhu",
            "--line",
            "Call of Cthulhu",
            "--trim-title",
            "Call of Cthulhu:",
            "--yes",
        )
        == 0
    )
    assert lines_of(db_path)["Arkham"] == "Call of Cthulhu"
    assert run(db_path, "import", str(export)) == 0
    assert lines_of(db_path)["Arkham"] == "Call of Cthulhu"  # the unchanged row left it alone
    assert run(db_path, "import", str(export), "--remap") == 0
    # --remap re-applies the export's title; the line it doesn't supply is kept
    assert lines_of(db_path)["Call of Cthulhu: Arkham"] == "Call of Cthulhu"


# ---------------------------------------------------------------- trim_prefix and parse_ids


@pytest.mark.parametrize(
    ("title", "prefix", "expected"),
    [
        ("Call of Cthulhu: Arkham Unveiled", "Call of Cthulhu", "Arkham Unveiled"),
        ("Call of Cthulhu: Arkham", "Call of Cthulhu:", "Arkham"),
        ("call of cthulhu - Arkham", "Call of Cthulhu:", "Arkham"),  # any separator, any case
        ("Call  of Cthulhu Keeper Screen", "call of cthulhu", "Keeper Screen"),
        ("Call of Cthulhuism", "Call of Cthulhu", "Call of Cthulhuism"),  # whole words only
        ("Call of Cthulhu", "Call of Cthulhu", "Call of Cthulhu"),  # would leave nothing
        ("Arkham", "Call of Cthulhu", "Arkham"),
        ("DND 3.5 Monster Manual", "DND 3.5", "Monster Manual"),
        ("DND 3.55", "DND 3.5", "DND 3.55"),
    ],
)
def test_trim_prefix(title, prefix, expected):
    assert trim_prefix(title, prefix) == expected


def test_parse_ids():
    assert parse_ids("3, 5,9-12,#14") == {3, 5, 9, 10, 11, 12, 14}
    for bad in ("x", "5-3", "1-999999"):
        with pytest.raises(ValueError):
            parse_ids(bad)


# ---------------------------------------------------------------- edit-many


@pytest.fixture
def shelf(db_path):
    with closing(connect(db_path)) as conn, conn:
        for title, tags in [
            ("Call of Cthulhu: Arkham", ["Horror"]),
            ("Call of Cthulhu Keeper Rulebook", ["Horror", "Core"]),
            ("Pulp Cthulhu", ["Horror"]),
            ("Mouse Guard", ["Core"]),
        ]:
            add_book(conn, NewBook(title=title, tags=tags))
    return db_path


def titles(db_path):
    return [t for (t,) in rows(db_path, "SELECT title FROM books ORDER BY book_id")]


def test_edit_many_needs_filters_and_changes(shelf, capsys):
    assert run(shelf, "edit-many", "--line", "X", "--yes") == 1
    assert "Choose the books" in capsys.readouterr().err
    assert run(shelf, "edit-many", "--all", "--yes") == 1
    assert "Nothing to change" in capsys.readouterr().err
    assert run(shelf, "edit-many", "--title-has", "dune", "--line", "X", "--yes") == 1
    assert "No books match" in capsys.readouterr().out


def test_edit_many_shows_changes_then_needs_yes(shelf, capsys):
    capsys.readouterr()
    assert (
        run(shelf, "edit-many", "--title-has", "call of cthulhu", "--line", "Call of Cthulhu") == 1
    )
    out = capsys.readouterr().out
    assert "2 books match." in out
    assert "Book 1: Call of Cthulhu: Arkham\n  line: (empty)  ->  Call of Cthulhu" in out
    assert "Not saved" in out
    assert set(lines_of(shelf).values()) == {None}


def test_edit_many_dry_run_saves_nothing(shelf, capsys):
    assert run(shelf, "edit-many", "--all", "--add-tag", "RPG", "--dry-run") == 0
    assert "Dry run" in capsys.readouterr().out
    assert rows(shelf, "SELECT count(*) FROM tags WHERE name = 'RPG'") == [(0,)]


def test_edit_many_title_has_matches_whole_words_in_title(shelf):
    run(shelf, "edit-many", "--title-has", "cthulhu", "--line", "Chaosium", "--yes")
    assert lines_of(shelf) == {
        "Call of Cthulhu: Arkham": "Chaosium",
        "Call of Cthulhu Keeper Rulebook": "Chaosium",
        "Pulp Cthulhu": "Chaosium",
        "Mouse Guard": None,
    }


def test_edit_many_filters_combine(shelf):
    assert (
        run(
            shelf,
            "edit-many",
            "--has-tag",
            "horror",
            "--has-tag",
            "core",
            "--add-tag",
            "X",
            "--yes",
        )
        == 0
    )
    tagged = rows(
        shelf,
        "SELECT b.title FROM books b JOIN book_tags USING (book_id) JOIN tags t USING (tag_id) "
        "WHERE t.name = 'X'",
    )
    assert tagged == [("Call of Cthulhu Keeper Rulebook",)]
    run(shelf, "edit-many", "--ids", "1-4", "--except", "2,3", "--shelf", "A1", "--yes")
    assert rows(shelf, "SELECT book_id FROM books WHERE shelf = 'A1'") == [(1,), (4,)]
    run(shelf, "edit-many", "--in-line", "nothing", "--shelf", "B", "--yes")
    run(shelf, "edit-many", "--match", "pulp", "--series", "Pulp", "--yes")
    assert rows(shelf, "SELECT b.title FROM books b JOIN series USING (series_id)") == [
        ("Pulp Cthulhu",)
    ]


def test_edit_many_trim_and_line_together(shelf):
    assert (
        run(
            shelf,
            "edit-many",
            "--title-has",
            "call of cthulhu",
            "--line",
            "Call of Cthulhu",
            "--trim-title",
            "Call of Cthulhu:",
            "--yes",
        )
        == 0
    )
    assert titles(shelf) == ["Arkham", "Keeper Rulebook", "Pulp Cthulhu", "Mouse Guard"]
    # the natural key now carries the line, so the trimmed title still identifies the book
    assert "call of cthulhu" in rows(shelf, "SELECT natural_key FROM books WHERE book_id = 1")[0][0]
    # in-line finds them now; a second trim changes nothing
    assert (
        run(
            shelf,
            "edit-many",
            "--in-line",
            "call of cthulhu",
            "--trim-title",
            "Call of Cthulhu",
            "-y",
        )
        == 0
    )
    assert titles(shelf)[:2] == ["Arkham", "Keeper Rulebook"]


def test_edit_many_refusal_rolls_back_everything(shelf, capsys):
    with closing(connect(shelf)) as conn, conn:
        conn.execute("INSERT INTO book_private (book_id, loaned_to) VALUES (3, 'Sam')")
    # a loan date without a borrower is refused for books 1 and 2, which come first
    assert (
        run(
            shelf,
            "edit-many",
            "--title-has",
            "cthulhu",
            "--loaned-on",
            "2026-01-02",
            "--line",
            "L",
            "-y",
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "Book 1 (Call of Cthulhu: Arkham)" in err and "Nothing changed" in err
    assert set(lines_of(shelf).values()) == {None}
    assert rows(shelf, "SELECT count(*) FROM product_lines") == [(0,)]


def test_edit_many_skips_removed_books_unless_asked(shelf):
    run(shelf, "edit", "4", "--remove", "-y")
    run(shelf, "edit-many", "--all", "--shelf", "S", "-y")
    assert rows(shelf, "SELECT book_id FROM books WHERE shelf = 'S'") == [(1,), (2,), (3,)]
    run(shelf, "edit-many", "--all", "--include-removed", "--shelf", "T", "-y")
    assert rows(shelf, "SELECT count(*) FROM books WHERE shelf = 'T'") == [(4,)]


def test_edit_many_has_no_single_book_options(shelf):
    for option in ("--title", "--isbn", "--volume", "--cover", "--ol-key"):
        with pytest.raises(SystemExit):
            run(shelf, "edit-many", "--all", option, "1")


def test_unmapped_columns_coming_and_going_count_as_unchanged(db_path, tmp_path):
    """The real case: the first export had image file names, a later one had no image column."""
    from tests.test_import import HEADER

    with_images = [
        dict(b, item_images=f"{b['item_id']}.jpg", item_updated="2023-01-01") for b in BOOKS
    ]
    import_file(db_path, write_export(tmp_path / "a.csv", with_images, HEADER), MAPPING)
    with closing(connect(db_path)) as conn, conn:
        conn.execute("UPDATE books SET title = 'My Fix' WHERE title = 'Feng Shui'")
    no_images = [h for h in HEADER if h != "item images"]
    touched = [dict(b, item_updated="2026-11-19") for b in BOOKS]
    report = import_file(db_path, write_export(tmp_path / "b.csv", touched, no_images), MAPPING)
    assert (report.updated, report.unchanged) == (0, 3)
    assert "My Fix" in lines_of(db_path)


def test_rows_hashed_by_v1_upgrade_without_overwriting(db_path, tmp_path):
    from tests.test_import import HEADER

    with_images = [dict(b, item_images="x.jpg") for b in BOOKS]
    import_file(db_path, write_export(tmp_path / "a.csv", with_images, HEADER), MAPPING)
    with closing(connect(db_path)) as conn, conn:
        conn.execute("UPDATE source_records SET row_hash = 'cells-v1:0123'")
        conn.execute("UPDATE books SET title = 'My Fix' WHERE title = 'Feng Shui'")
    no_images = [h for h in HEADER if h != "item images"]
    report = import_file(db_path, write_export(tmp_path / "b.csv", BOOKS, no_images), MAPPING)
    assert (report.updated, report.unchanged) == (0, 3)
    assert "My Fix" in lines_of(db_path)
