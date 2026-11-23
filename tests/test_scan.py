"""`bookshelf scan`, barcodes that aren't ISBNs, and edit --hidden/--public."""

import builtins
import io
from contextlib import closing

import pytest

from bookshelf import cli_books
from bookshelf.catalog import Credit, NewBook, add_book
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.export import public_books
from bookshelf.isbn import canonical_barcode, clean_scan
from bookshelf.openlibrary import Found, LookupFailed
from bookshelf.scan import Defaults, Session
from bookshelf.search import search

PHB = "9780786928866"
ANATHEM = "9780061474095"
UPC = "070004004007"  # a made-up UPC-A with a valid check digit
UPC_STORED = "0" + UPC


def run(db_path, *args):
    return main(["--db", str(db_path), *args])


class Script:
    """Feeds typed lines to the session and keeps what it printed."""

    def __init__(self, *lines):
        self.lines = list(lines)
        self.out: list[str] = []

    def read(self, prompt):
        self.out.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)

    def say(self, text):
        self.out.append(text)

    @property
    def text(self):
        return "\n".join(self.out)


KNOWN = {PHB: Found(title="Player's Handbook", authors=["Jonathan Tweet"], pub_year=2003)}


def typing(*lines):
    """A stand-in for input(): the lines, then end of input (like Ctrl+Z, Enter)."""
    queue = list(lines)

    def read(prompt=""):
        if not queue:
            raise EOFError
        return queue.pop(0)

    return read


def session(db, *lines, lookup=KNOWN.get, **kw):
    script = Script(*lines)
    s = Session(db, lookup, script.read, script.say, bell=False, today=lambda: "2026-11-23", **kw)
    return s, script


def rows(db, sql, params=()):
    return [tuple(r) for r in db.execute(sql, params)]


# ---------------------------------------------------------------- the barcode helpers


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        (UPC, UPC_STORED),  # UPC-A gets its leading 0
        (UPC_STORED, UPC_STORED),
        ("96385074", "96385074"),  # EAN-8
        (PHB, PHB),  # an ISBN is a valid EAN-13 too
        ("070004004001", None),  # bad check digit (7 is right)
        ("1234", None),
        ("hello", None),
    ],
)
def test_canonical_barcode(typed, expected):
    assert canonical_barcode(typed) == expected


def test_clean_scan_drops_price_add_on():
    assert clean_scan("9780786928866 51995") == PHB
    assert clean_scan("978078692886651995") == PHB
    assert clean_scan(UPC + "12") == UPC
    assert clean_scan("12345") == "12345"


# ---------------------------------------------------------------- scanning


def test_scan_adds_from_open_library_with_session_defaults(db):
    s, script = session(
        db, PHB, defaults=Defaults(shelf="Office 3", tags=["TTRPG"], line="DND 3.5")
    )
    counts = s.run()
    (book,) = db.execute("SELECT * FROM books").fetchall()
    assert (book["title"], book["isbn13"], book["pub_year"], book["shelf"], book["is_public"]) == (
        "Player's Handbook",
        PHB,
        2003,
        "Office 3",
        1,
    )
    assert rows(db, "SELECT name FROM product_lines") == [("DND 3.5",)]
    assert rows(db, "SELECT name FROM tags") == [("TTRPG",)]
    assert "Added #1  Player's Handbook — Jonathan Tweet — 2003" in script.text
    assert counts.added == 1 and "Done: added 1." in script.text


def test_scan_with_price_add_on_and_hyphens(db):
    s, _ = session(db, "9780786928866 51995", "q")
    s.run()
    assert rows(db, "SELECT isbn13 FROM books") == [(PHB,)]


def test_already_owned_then_another_copy_then_undo(db):
    s, script = session(db, PHB, PHB, "+", "u", "u")
    counts = s.run()
    assert (
        "Already have #1 Player's Handbook (1 copy). Type + if this is another copy." in script.text
    )
    assert "You now have 2 copies of #1 Player's Handbook." in script.text
    assert "Undone: one copy fewer of #1." in script.text
    assert "Undone: removed #1 Player's Handbook." in script.text
    assert rows(db, "SELECT count(*) FROM books") == [(0,)]
    assert (counts.added, counts.copies, counts.already) == (0, 0, 1)


def test_unknown_isbn_asks_for_title_and_authors(db):
    s, _ = session(db, ANATHEM, "Anathem", "Neal Stephenson; ")
    s.run()
    book = db.execute("SELECT * FROM books").fetchone()
    assert (book["title"], book["isbn13"], book["is_public"]) == ("Anathem", ANATHEM, 1)
    assert rows(db, "SELECT display_name FROM authors") == [("Neal Stephenson",)]


def test_unknown_isbn_left_blank_is_saved_hidden_for_later(db):
    s, script = session(db, ANATHEM, "")
    counts = s.run()
    book = db.execute("SELECT * FROM books").fetchone()
    assert (book["title"], book["is_public"]) == (f"ISBN {ANATHEM}", 0)
    (flag,) = rows(db, "SELECT reason, details FROM review_flags")
    assert flag[0] == "needs_details" and 'bookshelf edit 1 --title "..." --public' in flag[1]
    assert counts.later == 1 and "(1 to fill in later)" in script.text


def test_upc_then_isbn_from_copyright_page(db):
    s, script = session(db, UPC, PHB, UPC)
    counts = s.run()
    assert rows(db, "SELECT title, isbn13, barcode FROM books") == [
        ("Player's Handbook", PHB, UPC_STORED)
    ]
    assert "Already have #1" in script.text.split("Added #1")[1]  # the second scan finds it
    assert (counts.added, counts.already) == (1, 1)


def test_upc_then_title(db):
    s, _ = session(db, UPC, "Feng Shui", "Robin D. Laws")
    s.run()
    assert rows(db, "SELECT title, isbn13, barcode FROM books") == [("Feng Shui", None, UPC_STORED)]


def test_upc_left_blank_is_saved_for_later(db):
    s, _ = session(db, UPC, "")
    s.run()
    assert rows(db, "SELECT title, barcode, is_public FROM books") == [
        (f"Barcode {UPC_STORED}", UPC_STORED, 0)
    ]


def test_upc_then_bad_isbn_asks_again(db):
    add_book(db, NewBook(title="Player's Handbook", isbn=PHB))
    db.commit()
    s, script = session(db, UPC, "9780786928867", PHB)
    s.run()
    assert "Not a valid ISBN (bad check digit); try again." in script.text
    assert rows(db, "SELECT barcode FROM books") == [(UPC_STORED,)]
    s, script = session(db, "u")
    s.run()  # a new session has nothing to undo
    assert "Nothing to undo" in script.text


def test_attached_barcode_can_be_undone(db):
    add_book(db, NewBook(title="Player's Handbook", isbn=PHB))
    db.commit()
    s, script = session(db, UPC, PHB, "u")
    s.run()
    assert f"Undone: took barcode {UPC_STORED} off #1." in script.text
    assert rows(db, "SELECT barcode FROM books") == [(None,)]


def test_bad_input_changes_nothing(db):
    s, script = session(db, "9780786928867", "hello there", "+", "u", "", "?")
    s.run()
    assert "isn't a valid ISBN (bad check digit)" in script.text
    assert "'hello there' isn't a barcode" in script.text
    assert "Scan a book first" in script.text
    assert "Nothing to undo" in script.text
    assert rows(db, "SELECT count(*) FROM books") == [(0,)]


def test_open_library_down_switches_to_offline(db):
    calls = []

    def failing(isbn):
        calls.append(isbn)
        raise LookupFailed("Open Library didn't answer")

    s, script = session(db, PHB, "Player's Handbook", "", ANATHEM, "", lookup=failing)
    s.run()
    assert calls == [PHB]  # not asked again
    assert "Carrying on without Open Library" in script.text
    assert rows(db, "SELECT title FROM books ORDER BY book_id") == [
        ("Player's Handbook",),
        (f"ISBN {ANATHEM}",),
    ]


def test_removed_book_is_not_added_again(db):
    book_id = add_book(db, NewBook(title="Player's Handbook", isbn=PHB))
    db.execute("UPDATE books SET removed_on = '2026-01-01' WHERE book_id = ?", (book_id,))
    db.commit()
    s, script = session(db, PHB)
    s.run()
    assert "marked removed on 2026-01-01" in script.text and "--restore" in script.text
    assert rows(db, "SELECT count(*) FROM books") == [(1,)]


def test_possible_duplicate_is_flagged(db):
    add_book(
        db, NewBook(title="Player's Handbook", credits=[Credit("Jonathan Tweet")], pub_year=2003)
    )
    db.commit()
    s, script = session(db, PHB)
    s.run()
    assert "Careful: this looks like book #1" in script.text
    assert rows(db, "SELECT reason, candidate_book_id FROM review_flags") == [
        ("possible_duplicate", 1)
    ]


def test_session_hidden_and_ol_key_already_used(db):
    known = {PHB: Found(title="Player's Handbook", ol_edition_key="OL1M")}
    add_book(db, NewBook(title="Other", ol_edition_key="OL1M"))
    db.commit()
    s, _ = session(db, PHB, lookup=known.get, defaults=Defaults(hidden=True))
    s.run()
    assert rows(db, "SELECT is_public, ol_edition_key FROM books WHERE isbn13 = ?", (PHB,)) == [
        (0, None)
    ]


# ---------------------------------------------------------------- the command


def test_scan_command(db_path, monkeypatch, capsys):
    monkeypatch.setattr(builtins, "input", typing(PHB, "Player's Handbook", "Jonathan Tweet", "q"))
    assert run(db_path, "scan", "--offline", "--shelf", "A1", "--condition", "very good") == 0
    out = capsys.readouterr().out
    assert "Added #1  Player's Handbook — Jonathan Tweet" in out
    assert "Run 'bookshelf publish'" in out
    with closing(connect(db_path)) as conn:
        assert rows(conn, "SELECT shelf, condition FROM books") == [("A1", "very_good")]


def test_scan_command_end_of_input(db_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert run(db_path, "scan", "--offline") == 0
    assert "Done: added 0." in capsys.readouterr().out


def test_scan_command_rejects_unknown_condition(db_path, capsys):
    assert run(db_path, "scan", "--condition", "shiny") == 1
    assert "unknown condition" in capsys.readouterr().err


def test_scan_command_uses_open_library(db_path, monkeypatch, capsys):
    class FakeOL:
        def __init__(self, conn):
            pass

        def lookup(self, isbn):
            return KNOWN.get(isbn)

    monkeypatch.setattr(cli_books, "OpenLibrary", FakeOL)
    monkeypatch.setattr(builtins, "input", typing(PHB))
    assert run(db_path, "scan", "--quiet") == 0
    assert "Added #1  Player's Handbook" in capsys.readouterr().out


# ---------------------------------------------------------------- barcodes elsewhere


def test_search_and_export_by_barcode(db):
    add_book(db, NewBook(title="Feng Shui", barcode=UPC_STORED))
    books = public_books(db)
    assert books[0]["barcode"] == UPC_STORED
    for typed in (UPC, UPC_STORED, UPC + "12"):
        result = search(books, typed)
        assert (result.mode, [b["title"] for b in result.books]) == ("barcode", ["Feng Shui"])
    assert search(books, "9780786928866 51995").mode == "isbn"
    assert search(books, "070004004001").mode == "text"  # bad check digit: just digits


def test_edit_barcode_and_visibility(db_path, capsys):
    run(db_path, "add", "--title", "Feng Shui", "--offline", "-y")
    assert run(db_path, "edit", "1", "--barcode", UPC, "--hidden", "-y") == 0
    with closing(connect(db_path)) as conn:
        assert rows(conn, "SELECT barcode, is_public FROM books") == [(UPC_STORED, 0)]
    assert run(db_path, "edit", "1", "--public", "-y") == 0
    assert run(db_path, "edit", "1", "--barcode", "070004004001", "-y") == 1
    assert run(db_path, "edit", "1", "--barcode", PHB, "-y") == 1
    assert "use --isbn" in capsys.readouterr().err
    assert run(db_path, "edit", "1", "--hidden", "--public", "-y") == 1
    assert run(db_path, "edit", "1", "--clear", "barcode", "-y") == 0
    with closing(connect(db_path)) as conn:
        assert rows(conn, "SELECT barcode, is_public FROM books") == [(None, 1)]


def test_add_with_barcode(db_path, capsys):
    assert run(db_path, "add", "--title", "Feng Shui", "--barcode", UPC, "--offline", "-y") == 0
    with closing(connect(db_path)) as conn:
        assert rows(conn, "SELECT barcode FROM books") == [(UPC_STORED,)]
    assert run(db_path, "add", "--title", "X", "--barcode", "1234", "--offline", "-y") == 1


def test_offline_says_not_looked_up(db):
    s, script = session(db, ANATHEM, "Anathem", "", lookup=None)
    s.run()
    assert "not looked up" in script.text and "doesn't know" not in script.text
