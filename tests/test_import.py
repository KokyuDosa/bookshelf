"""The import pipeline end to end, against small synthetic exports."""

import csv
import sqlite3
import zipfile
from contextlib import closing

import pytest

from bookshelf.catalog import NewBook, add_book
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.importers.mapping import Mapping
from bookshelf.importers.pipeline import import_file
from bookshelf.paths import PROJECT_ROOT

MAPPING = Mapping.load(PROJECT_ROOT / "config" / "mappings" / "mystuff2.toml")
HEADER = [
    "item id",
    "item container",
    "title",
    "author",
    "publisher",
    "genre",
    "pages",
    "edition",
    "quality",
    "price",
    "item barcode",
    "item images",
    "item updated",
    "item created",
]


def write_export(path, rows, header=HEADER, bom=True):
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k.replace("_", " "): v for k, v in r.items()})
    return path


BOOKS = [
    {
        "item_id": "A",
        "title": "DND 3.5; Player's Handbook (2 Copies)",
        "genre": "TTRPG",
        "price": "$71.16",
        "item_barcode": "9780786928866",
        "quality": "Like New",
    },
    {
        "item_id": "B",
        "title": "Feng Shui",
        "author": "Robin D. Laws",
        "item_barcode": "700040040004",  # neither an ISBN nor a UPC (bad check digit)
    },
    {
        "item_id": "C",
        "title": "Call of Cthulhu: Arkham",
        "author": "Bret Kramer|Mike Mason",
        "edition": "7th",
        "publisher": "Chaosium Inc.",
        "item_images": "C/1.jpeg",
    },
]


@pytest.fixture
def export(tmp_path):
    return write_export(tmp_path / "Books.csv", BOOKS)


def books(db_path):
    with closing(connect(db_path)) as conn:
        return {r["title"]: dict(r) for r in conn.execute("SELECT * FROM books")}


def test_first_import(db_path, export):
    report = import_file(db_path, export, MAPPING)
    assert (report.rows_read, report.inserted, report.rejected) == (3, 3, 0)
    stored = books(db_path)
    assert stored["Player's Handbook"]["copies"] == 2
    arkham = stored["Call of Cthulhu: Arkham"]  # a colon is not a series separator
    assert (arkham["series_id"], arkham["edition"], arkham["publisher"]) == (
        None,
        "7th",
        "Chaosium",
    )
    assert stored["Feng Shui"]["isbn13"] is None
    assert [(f.title, f.reason) for f in report.flags] == [("Feng Shui", "invalid_isbn")]
    assert report.backup_file and report.backup_file.exists()


def test_reimport_changes_nothing(db_path, export):
    import_file(db_path, export, MAPPING)
    again = import_file(db_path, export, MAPPING)
    assert (again.inserted, again.updated, again.unchanged, again.flags) == (0, 0, 3, [])


def test_changed_row_overwrites_but_keeps_enrichment(db_path, tmp_path, export):
    import_file(db_path, export, MAPPING)
    with closing(connect(db_path)) as conn, conn:
        conn.execute(
            "UPDATE books SET pub_year = 2002 WHERE title = 'Feng Shui'"
        )  # e.g. Open Library
    edited = [dict(b) for b in BOOKS]
    edited[1]["title"] = "Feng Shui: Action Movie Roleplaying"
    report = import_file(db_path, write_export(tmp_path / "Books2.csv", edited), MAPPING)
    assert (report.updated, report.unchanged) == (1, 2)
    row = books(db_path)["Feng Shui: Action Movie Roleplaying"]
    assert row["pub_year"] == 2002
    assert row["natural_key"] == "feng shui action movie roleplaying|laws robin d|2002"


def test_isbn_match_fills_gaps_in_existing_book(db_path, export):
    with closing(connect(db_path)) as conn, conn:
        add_book(conn, NewBook("PHB 3.5", isbn="0-7869-2886-7", pub_year=2003))
    report = import_file(db_path, export, MAPPING)
    assert (report.inserted, report.updated) == (2, 1)
    phb = books(db_path)["PHB 3.5"]  # your title wins; the import only fills empty fields
    assert phb["condition"] == "like_new" and phb["copies"] == 1 and phb["pub_year"] == 2003


def test_possible_duplicate_is_flagged(db_path, tmp_path):
    rows = [
        {"item_id": "X", "title": "Microscope", "author": "Ben Robbins"},
        {"item_id": "Y", "title": "Microscope", "author": "Ben Robbins"},
    ]
    report = import_file(db_path, write_export(tmp_path / "d.csv", rows), MAPPING)
    assert report.inserted == 2
    assert [f.reason for f in report.flags] == ["possible_duplicate"]
    with closing(connect(db_path)) as conn:
        first, second = [r[0] for r in conn.execute("SELECT book_id FROM books ORDER BY book_id")]
        flag = conn.execute("SELECT book_id, candidate_book_id FROM review_flags").fetchone()
    assert tuple(flag) == (second, first)


def test_series_keeps_same_titles_apart(db_path, tmp_path):
    rows = [
        {"item_id": "X", "title": "Ashen Stars; Core Rulebook"},
        {"item_id": "Y", "title": "Cyberpunk Red; Core Rulebook"},
    ]
    report = import_file(db_path, write_export(tmp_path / "s.csv", rows), MAPPING)
    assert report.flags == []


def test_bad_rows_are_rejected_and_written_out(db_path, tmp_path):
    rows = [*BOOKS, {"item_id": "D", "title": ""}, {"item_id": "A", "title": "Duplicate key"}]
    report = import_file(db_path, write_export(tmp_path / "bad.csv", rows), MAPPING)
    assert (report.inserted, report.rejected) == (3, 2)
    with report.rejects_file.open(encoding="utf-8-sig") as f:
        reasons = [r["reason"] for r in csv.DictReader(f)]
    assert reasons == ["no title", "item A appears twice in this file"]


def test_dry_run_saves_nothing(db_path, export):
    report = import_file(db_path, export, MAPPING, dry_run=True)
    assert report.inserted == 3 and report.backup_file is None
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT count(*) FROM books").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM import_runs").fetchone()[0] == 0


def test_corrections_are_applied(db_path, export):
    corrections = {
        "B": {"item barcode": "", "title": "Feng Shui (Hardcover)"},
        "ZZZ": {"title": "nobody"},
    }
    report = import_file(db_path, export, MAPPING, corrections)
    assert books(db_path)["Feng Shui"]["format"] == "hardcover"
    assert report.flags == []
    assert report.warnings == ["correction for ZZZ matched no row in this file"]


def test_correction_with_unknown_column_rejects_row(db_path, export):
    report = import_file(db_path, export, MAPPING, {"B": {"titel": "typo"}})
    assert report.rejected == 1 and "unknown column" in report.rejects[0]["reason"]


def test_resolved_flags_stay_resolved(db_path, tmp_path, export):
    import_file(db_path, export, MAPPING)
    assert main(["--db", str(db_path), "review", "--resolve", "1", "ignored"]) == 0
    edited = [dict(b) for b in BOOKS]
    edited[1]["publisher"] = "Atlas Games"  # row changes, but the barcode is still bad
    report = import_file(db_path, write_export(tmp_path / "e.csv", edited), MAPPING)
    assert report.updated == 1 and report.flags == []


def test_zip_of_categories_and_missing_columns(db_path, tmp_path):
    novels = write_export(
        tmp_path / "Novels.csv",
        [{"item_id": "N1", "title": "Dune"}],
        header=["item id", "title"],
        bom=False,
    )
    games = write_export(tmp_path / "Games.csv", BOOKS)
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.write(novels, "Novels.csv")
        z.write(games, "Games.csv")
        z.writestr("images/x.jpeg", b"not a csv")
    report = import_file(db_path, archive, MAPPING)
    assert report.inserted == 4
    assert any("Novels.csv: no column(s)" in w for w in report.warnings)


def test_wrong_file_is_refused_and_saves_nothing(db_path, tmp_path):
    other = write_export(tmp_path / "x.csv", [{"name": "x"}], header=["name"])
    with pytest.raises(ValueError, match="no 'item id' column"):
        import_file(db_path, other, MAPPING)
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT count(*) FROM import_runs").fetchone()[0] == 0


def test_cli_import_and_review(db_path, export, capsys):
    assert main(["--db", str(db_path), "import", str(export), "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert main(["--db", str(db_path), "import", str(export)]) == 0
    assert main(["--db", str(db_path), "review"]) == 0
    assert "Feng Shui" in capsys.readouterr().out
    assert main(["--db", str(db_path), "review", "--resolve", "1", "bogus"]) == 1
