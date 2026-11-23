"""`bookshelf scan`: add books by scanning their barcodes, one after another.

A USB barcode scanner acts as a keyboard: it types the code and presses Enter. So a scan
session is a loop reading lines. Each new book is saved at once (one transaction per book,
so nothing is lost if the window closes); `u` undoes the last thing saved.
"""

import datetime as dt
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

from bookshelf.catalog import Credit, NewBook, add_book, find_by_natural_key
from bookshelf.entry import find_owned
from bookshelf.isbn import InvalidISBN, canonical_barcode, clean_scan, looks_like_isbn, to_isbn13
from bookshelf.normalize import normalize_text
from bookshelf.openlibrary import Found, LookupFailed

HELP = (
    "Scan a barcode (or type an ISBN) and press Enter.  "
    "u = undo the last one, + = another copy of the book just scanned, q = finish"
)


@dataclass
class Defaults:
    """Values given on the command line, applied to every book the session adds."""

    shelf: str | None = None
    tags: list[str] = field(default_factory=list)
    line: str | None = None
    condition: str | None = None
    format: str | None = None
    hidden: bool = False


@dataclass
class Counts:
    added: int = 0
    later: int = 0  # saved hidden with a review flag: details to fill in
    copies: int = 0
    already: int = 0

    def summary(self) -> str:
        bits = [f"added {self.added}" + (f" ({self.later} to fill in later)" if self.later else "")]
        if self.copies:
            bits.append(f"{self.copies} more {'copy' if self.copies == 1 else 'copies'}")
        if self.already:
            bits.append(f"{self.already} you already had")
        return "Done: " + ", ".join(bits) + "."


def _label(row: sqlite3.Row) -> str:
    return "; ".join(p for p in (row["line"], row["series"], row["title"]) if p)


class Session:
    def __init__(
        self,
        conn: sqlite3.Connection,
        lookup: Callable[[str], Found | None] | None,
        read: Callable[[str], str],
        say: Callable[[str], None] = print,
        defaults: Defaults | None = None,
        bell: bool = True,
        today: Callable[[], str] = lambda: dt.date.today().isoformat(),
    ):
        self.conn = conn
        self.lookup = lookup  # None: offline
        self.read = read
        self.say = say
        self.defaults = defaults or Defaults()
        self.bell = "\a" if bell else ""
        self.today = today
        self.counts = Counts()
        self.undo: list[tuple[str, Callable[[], None]]] = []
        self.last_seen: int | None = None  # book the + command adds a copy to

    # ------------------------------------------------------------ the loop

    def run(self) -> Counts:
        self.say(HELP)
        while True:
            try:
                line = self.read("scan> ")
            except (EOFError, KeyboardInterrupt):
                break
            if line.strip().lower() in ("q", "quit", "exit", "done"):
                break
            try:
                self.handle(line)
            except (EOFError, KeyboardInterrupt):
                break
        self.say(self.counts.summary())
        return self.counts

    def handle(self, line: str) -> None:
        text = line.strip()
        if not text:
            return
        command = text.lower()
        if command in ("u", "undo"):
            return self._undo()
        if command == "+":
            return self._another_copy()
        if command in ("?", "h", "help"):
            return self.say(HELP)

        code = canonical_barcode(text)  # also drops a scanned price add-on
        try:
            isbn = to_isbn13(code if code and code[:3] in ("978", "979") else clean_scan(text))
        except InvalidISBN as exc:
            if code:
                return self._barcode(code)
            if looks_like_isbn(text):
                return self._warn(f"{text} isn't a valid ISBN ({exc.reason.replace('_', ' ')}).")
            return self._warn(f"{text!r} isn't a barcode or an ISBN (? lists the commands).")
        self._isbn(isbn)

    # ------------------------------------------------------------ scans

    def _isbn(self, isbn13: str, barcode: str | None = None) -> None:
        owned = find_owned(self.conn, isbn13)
        if owned:
            self._already(owned)
            if barcode:
                self._attach_barcode(owned["book_id"], barcode)
            return
        removed = self.conn.execute(
            "SELECT book_id, title, removed_on FROM books WHERE isbn13 = ?", (isbn13,)
        ).fetchone()
        if removed:
            return self._warn(
                f"That's book #{removed['book_id']} ({removed['title']}), marked removed on "
                f"{removed['removed_on']}. To bring it back: "
                f"bookshelf edit {removed['book_id']} --restore"
            )

        asked = self.lookup is not None
        found = self._lookup(isbn13)
        if found:
            book = NewBook(
                title=found.title,
                subtitle=found.subtitle,
                credits=[Credit(a) for a in found.authors],
                publisher=found.publisher,
                pub_year=found.pub_year,
                pages=found.pages,
                cover_url=found.cover_url,
                ol_edition_key=found.ol_edition_key,
            )
        else:
            if asked and self.lookup is not None:
                self.say(f"{self.bell}  Open Library doesn't know ISBN {isbn13}.")
            else:
                self.say(f"  ISBN {isbn13}: not looked up (no Open Library this session).")
            book = self._ask_details(placeholder=f"ISBN {isbn13}")
        book.isbn, book.barcode = isbn13, barcode
        self._save(book, placeholder=book.title == f"ISBN {isbn13}" and not found)

    def _barcode(self, code: str) -> None:
        owned = self.conn.execute(
            "SELECT b.book_id, b.title, b.copies, pl.name AS line, s.name AS series "
            "FROM active_books b LEFT JOIN series s USING (series_id) "
            "LEFT JOIN product_lines pl USING (line_id) WHERE b.barcode = ? ORDER BY b.book_id",
            (code,),
        ).fetchall()
        if len(owned) == 1:
            return self._already(owned[0])
        if owned:
            self.counts.already += 1
            self.last_seen = None
            listed = "; ".join(f"#{r['book_id']} {_label(r)}" for r in owned)
            return self.say(
                f"{self.bell}  Already have {len(owned)} books with that barcode: {listed}"
            )

        self.say(f"  Barcode {code} isn't an ISBN (a UPC or store code).")
        while True:
            reply = self.read(
                "  Type the ISBN from the copyright page, or the title (Enter = fill in later): "
            ).strip()
            if not reply or not looks_like_isbn(reply):
                break
            try:
                return self._isbn(to_isbn13(reply), barcode=code)
            except InvalidISBN as exc:
                self.say(
                    f"{self.bell}  Not a valid ISBN ({exc.reason.replace('_', ' ')}); try again."
                )
        book = self._ask_details(placeholder=f"Barcode {code}", title=reply)
        book.barcode = code
        self._save(book, placeholder=book.title == f"Barcode {code}")

    def _ask_details(self, placeholder: str, title: str | None = None) -> NewBook:
        """Title and authors typed now, or a hidden placeholder to fill in later."""
        if title is None:
            title = self.read("  Title (Enter = fill in later): ").strip()
        if normalize_text(title):
            names = self.read("  Authors, separated by ; (Enter to skip): ").split(";")
            return NewBook(title=title, credits=[Credit(n.strip()) for n in names if n.strip()])
        return NewBook(title=placeholder, is_public=False)

    # ------------------------------------------------------------ saving and undoing

    def _save(self, book: NewBook, placeholder: bool = False) -> None:
        """placeholder: saved without details, hidden, with a needs_details review flag."""
        d = self.defaults
        book.shelf, book.line, book.condition, book.format = d.shelf, d.line, d.condition, d.format
        book.tags = list(d.tags)
        if d.hidden:
            book.is_public = False
        if (
            book.ol_edition_key
            and self.conn.execute(
                "SELECT 1 FROM books WHERE ol_edition_key = ?", (book.ol_edition_key,)
            ).fetchone()
        ):
            book.ol_edition_key = None  # another of your books already holds that record
        with self.conn:
            duplicates = [] if placeholder else find_by_natural_key(self.conn, book)
            book_id = add_book(self.conn, book)
            if placeholder:
                self._flag(
                    book_id,
                    None,
                    "needs_details",
                    f"scanned {self.today()}; give it a title, then: bookshelf edit {book_id} "
                    '--title "..." --public',
                )
            elif duplicates:
                self._flag(
                    book_id,
                    duplicates[0],
                    "possible_duplicate",
                    f"scanned; resembles book {duplicates[0]}",
                )
        self.counts.added += 1
        self.counts.later += placeholder
        self.last_seen = book_id

        def undo() -> None:
            with self.conn:
                self.conn.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
            self.counts.added -= 1
            self.counts.later -= placeholder
            self.last_seen = None

        self.undo.append((f"removed #{book_id} {book.title}", undo))
        if placeholder:
            self.say(
                f"  Saved #{book_id} for later: hidden until you fill it in (bookshelf review)."
            )
            return
        authors = ", ".join(c.name for c in book.credits)
        details = " — ".join(str(p) for p in (book.title, authors, book.pub_year) if p)
        self.say(f"  Added #{book_id}  {details}")
        if duplicates:
            self.say(
                f"{self.bell}  Careful: this looks like book #{duplicates[0]}. Type u if it's the same."
            )

    def _flag(self, book_id: int, other: int | None, reason: str, details: str) -> None:
        self.conn.execute(
            "INSERT INTO review_flags (book_id, candidate_book_id, reason, details) VALUES (?, ?, ?, ?)",
            (book_id, other, reason, details),
        )

    def _already(self, row: sqlite3.Row) -> None:
        self.counts.already += 1
        self.last_seen = row["book_id"]
        copies = f"{row['copies']} {'copy' if row['copies'] == 1 else 'copies'}"
        self.say(
            f"{self.bell}  Already have #{row['book_id']} {_label(row)} ({copies}). "
            "Type + if this is another copy."
        )

    def _attach_barcode(self, book_id: int, code: str) -> None:
        has = self.conn.execute(
            "SELECT barcode FROM books WHERE book_id = ?", (book_id,)
        ).fetchone()[0]
        if has:
            return
        with self.conn:
            self.conn.execute("UPDATE books SET barcode = ? WHERE book_id = ?", (code, book_id))
        self.say(f"  Saved barcode {code} on it, so scanning that finds it next time.")

        def undo() -> None:
            with self.conn:
                self.conn.execute("UPDATE books SET barcode = NULL WHERE book_id = ?", (book_id,))

        self.undo.append((f"took barcode {code} off #{book_id}", undo))

    def _another_copy(self) -> None:
        if self.last_seen is None:
            return self._warn("Scan a book first; + adds a copy of the book just scanned.")
        book_id = self.last_seen
        with self.conn:
            copies = self.conn.execute(
                "UPDATE books SET copies = copies + 1 WHERE book_id = ? RETURNING copies, title",
                (book_id,),
            ).fetchone()
        self.counts.copies += 1
        self.say(f"  You now have {copies[0]} copies of #{book_id} {copies[1]}.")

        def undo() -> None:
            with self.conn:
                self.conn.execute(
                    "UPDATE books SET copies = copies - 1 WHERE book_id = ? AND copies > 1",
                    (book_id,),
                )
            self.counts.copies -= 1

        self.undo.append((f"one copy fewer of #{book_id}", undo))

    def _undo(self) -> None:
        if not self.undo:
            return self._warn("Nothing to undo in this session.")
        what, undo = self.undo.pop()
        undo()
        self.say(f"  Undone: {what}.")

    # ------------------------------------------------------------ helpers

    def _lookup(self, isbn13: str) -> Found | None:
        if self.lookup is None:
            return None
        try:
            return self.lookup(isbn13)
        except LookupFailed as exc:
            self.lookup = None  # don't wait on every scan; enrich can fill details later
            self.say(f"{self.bell}  {exc}. Carrying on without Open Library for this session.")
            return None

    def _warn(self, message: str) -> None:
        self.say(f"{self.bell}  {message}")
