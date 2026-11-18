"""Numbered volumes that share a title: "Happiness" volumes 1 to 10."""

from contextlib import closing

import pytest

from bookshelf.catalog import NewBook, add_book
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.export import public_books
from bookshelf.importers.mapping import Mapping, map_row, parse_volume, strip_volume
from bookshelf.importers.pipeline import import_file
from bookshelf.paths import PROJECT_ROOT
from bookshelf.search import describe
from tests.test_import import HEADER, write_export

MAPPING = Mapping.load(PROJECT_ROOT / "config" / "mappings" / "mystuff2.toml")
MANGA_HEADER = [*HEADER, "volume"]


def manga_rows(volumes, title="Happiness"):
    return [
        {"item_id": f"H{v}", "title": title, "author": "Shuzo Oshimi", "genre": "Manga",
         "volume": str(v)}
        for v in volumes
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("raw", "number"),
    [("3", 3.0), ("03", 3.0), ("2.5", 2.5), ("Vol. 3", 3.0), ("volume 12", 12.0), ("v7", 7.0),
     ("#4", 4.0), ("No. 5", 5.0), ("1-3", None), ("three", None), ("", None)],
)  # fmt: skip
def test_parse_volume(raw, number):
    assert parse_volume(raw) == number


@pytest.mark.parametrize(
    ("title", "volume", "expected"),
    [("Happiness, Vol. 3", 3, "Happiness"), ("Happiness 3", 3, "Happiness"),
     ("Happiness v03", 3, "Happiness"), ("Happiness, Vol. 3", 4, "Happiness, Vol. 3"),
     # a title ending in the volume's own number reads as repeating it, so only a
     # "Catch 22" whose volume column also says 22 would be trimmed
     ("Catch 22", 22, "Catch"), ("Catch 22", 1, "Catch 22"), ("22", 22, "22")],
)  # fmt: skip
def test_strip_volume(title, volume, expected):
    assert strip_volume(title, volume) == expected


def test_volume_without_series_makes_the_title_the_series():
    book = map_row({"item id": "1", "title": "Happiness, Vol. 3", "volume": "3"}, MAPPING).book
    assert (book.title, book.series, book.series_index) == ("Happiness", "Happiness", 3.0)


def test_series_column_and_title_prefix():
    m = Mapping.load(PROJECT_ROOT / "config" / "mappings" / "mystuff2.toml")
    m.fields["series"] = "series"
    book = map_row({"item id": "1", "title": "Berserk; Volume One", "series": "Berserk Deluxe",
                    "volume": "1"}, m).book  # fmt: skip
    assert (book.series, book.series_index) == ("Berserk Deluxe", 1.0)  # the column wins


def test_ten_volumes_import_without_duplicate_flags(db_path, tmp_path):
    export = write_export(tmp_path / "Manga.csv", manga_rows(range(1, 11)), header=MANGA_HEADER)
    report = import_file(db_path, export, MAPPING)
    assert (report.inserted, report.flags, report.notes) == (10, [], [])
    with closing(connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT b.title, s.name, b.series_index FROM books b JOIN series s USING (series_id) "
            "ORDER BY b.series_index"
        ).fetchall()
    assert [tuple(r) for r in rows] == [("Happiness", "Happiness", float(v)) for v in range(1, 11)]


def test_the_same_volume_twice_is_still_flagged(db_path, tmp_path):
    rows = manga_rows([3]) + [{**manga_rows([3])[0], "item_id": "OTHER"}]
    report = import_file(
        db_path, write_export(tmp_path / "m.csv", rows, header=MANGA_HEADER), MAPPING
    )
    assert [f.reason for f in report.flags] == ["possible_duplicate"]


def test_unreadable_volume_is_flagged_not_lost(db_path, tmp_path):
    rows = [{**manga_rows([1])[0], "volume": "1-3"}]
    report = import_file(
        db_path, write_export(tmp_path / "m.csv", rows, header=MANGA_HEADER), MAPPING
    )
    assert report.inserted == 1 and report.flags[0].details == "volume '1-3' is not a single number"


def test_category_without_volume_column_gets_a_note_not_a_warning(db_path, tmp_path):
    report = import_file(db_path, write_export(tmp_path / "Fiction.csv", manga_rows([1])), MAPPING)
    assert report.warnings == []
    assert report.notes == ["Fiction.csv: no 'volume' column (fine if this category has none)"]


def test_search_and_display_by_volume(db_path, tmp_path, capsys):
    import_file(
        db_path,
        write_export(tmp_path / "m.csv", manga_rows(range(1, 11)), header=MANGA_HEADER),
        MAPPING,
    )
    with closing(connect(db_path)) as conn:
        vol7 = next(b for b in public_books(conn) if b["volume"] == 7)
    assert vol7["key"] == "happiness happiness vol 7 shuzo oshimi"
    assert describe(vol7) == "Happiness  —  vol. 7  —  Shuzo Oshimi"
    for query in (["happiness", "7"], ["happiness", "vol", "7"]):
        assert main(["--db", str(db_path), "search", *query]) == 0
        assert (
            capsys.readouterr()
            .out.splitlines()[1]
            .endswith("Happiness  —  vol. 7  —  Shuzo Oshimi")
        )
    assert main(["--db", str(db_path), "show", "happiness", "7"]) == 0  # one match: shown directly
    assert "volume           7" in capsys.readouterr().out


def test_rekey_fixes_keys_made_before_volumes_counted(db_path, capsys):
    with closing(connect(db_path)) as conn, conn:
        for v in (1, 2):
            add_book(conn, NewBook("Happiness", series="Happiness", series_index=v))
        conn.execute(
            "UPDATE books SET natural_key = 'happiness happiness||'"
        )  # the old rule's keys
    assert main(["--db", str(db_path), "rekey"]) == 0
    assert "Recomputed the keys of 2 books; 2 changed." in capsys.readouterr().out
    with closing(connect(db_path)) as conn:
        keys = [r[0] for r in conn.execute("SELECT natural_key FROM books ORDER BY book_id")]
    assert keys == ["happiness vol 1 happiness||", "happiness vol 2 happiness||"]
    assert main(["--db", str(db_path), "rekey"]) == 0
    assert "0 changed" in capsys.readouterr().out
