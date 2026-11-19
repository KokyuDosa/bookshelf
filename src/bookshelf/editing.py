"""Finding one book, showing everything stored about it, and changing it."""

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass, field

from bookshelf.catalog import (
    Credit,
    Part,
    _add_credits,
    _add_tags,
    get_or_create_line,
    get_or_create_series,
    read_parts,
    refresh_keys,
    write_parts,
)
from bookshelf.export import public_books
from bookshelf.isbn import InvalidISBN, looks_like_isbn, to_isbn10, to_isbn13
from bookshelf.normalize import normalize_text
from bookshelf.search import describe, search

# ---------------------------------------------------------------- finding a book


@dataclass
class Found:
    book_id: int | None
    candidates: list[tuple[int, str]] = field(default_factory=list)  # when the words match several


def resolve(conn: sqlite3.Connection, ref: str) -> Found:
    """A book number ("57"), an ISBN in any form, or words from the title, line, series or authors.
    Numbers and ISBNs also find removed books, so they can be shown and restored."""
    ref = ref.strip().lstrip("#")
    if looks_like_isbn(ref):
        try:
            isbn = to_isbn13(ref)
        except InvalidISBN as exc:
            raise ValueError(
                f"{ref!r} isn't a valid ISBN ({exc.reason.replace('_', ' ')})"
            ) from None
        row = conn.execute("SELECT book_id FROM books WHERE isbn13 = ?", (isbn,)).fetchone()
        return Found(row[0] if row else None)
    if re.fullmatch(r"\d{1,9}", ref):
        row = conn.execute("SELECT book_id FROM books WHERE book_id = ?", (int(ref),)).fetchone()
        return Found(row[0] if row else None)
    hits = search(public_books(conn, include_hidden=True), ref).books
    if len(hits) == 1:
        return Found(hits[0]["id"])
    return Found(None, [(b["id"], describe(b)) for b in hits])


# ---------------------------------------------------------------- everything about one book


def details(conn: sqlite3.Connection, book_id: int) -> dict:
    b = conn.execute(
        "SELECT b.*, s.name AS series, pl.name AS line FROM books b "
        "LEFT JOIN series s USING (series_id) LEFT JOIN product_lines pl USING (line_id) "
        "WHERE b.book_id = ?",
        (book_id,),
    ).fetchone()
    private = conn.execute("SELECT * FROM book_private WHERE book_id = ?", (book_id,)).fetchone()
    credits = conn.execute(
        "SELECT a.author_id, a.display_name, ba.role, ba.position FROM book_authors ba "
        "JOIN authors a USING (author_id) WHERE ba.book_id = ? ORDER BY ba.position",
        (book_id,),
    ).fetchall()
    tags = conn.execute(
        "SELECT t.name FROM book_tags JOIN tags t USING (tag_id) WHERE book_id = ? ORDER BY t.name_key",
        (book_id,),
    ).fetchall()
    sources = conn.execute(
        "SELECT source, source_key, first_seen_run, last_seen_run FROM source_records WHERE book_id = ?",
        (book_id,),
    ).fetchall()
    flags = conn.execute(
        "SELECT flag_id, reason, details, resolved_at, resolution FROM review_flags "
        "WHERE book_id = ? OR candidate_book_id = ? ORDER BY flag_id",
        (book_id, book_id),
    ).fetchall()
    parts = read_parts(conn, book_id)
    isbn10 = to_isbn10(b["isbn13"]) if b["isbn13"] else None
    return {
        "id": b["book_id"],
        "title": b["title"],
        "subtitle": b["subtitle"],
        "line": b["line"],
        "series": b["series"],
        "volume": b["series_index"],
        "edition": b["edition"],
        "format": b["format"],
        "isbn13": b["isbn13"],
        "isbn10": isbn10,
        "publisher": b["publisher"],
        "year": b["pub_year"],
        "pages": b["pages"],
        "language": b["language"],
        "credits": [
            {"name": c["display_name"], "role": c["role"], "author_id": c["author_id"]}
            for c in credits
        ],
        "tags": [t[0] for t in tags],
        "parts": [{"kind": p.kind, "label": p.label, "have": p.have} for p in parts],
        "copies": b["copies"],
        "condition": b["condition"],
        "shelf": b["shelf"],
        "acquired": b["acquired_on"],
        "public": bool(b["is_public"]),
        "removed": b["removed_on"],
        "private": {
            "price_cents": private["purchase_price_cents"] if private else None,
            "value_cents": private["estimated_value_cents"] if private else None,
            "notes": private["notes"] if private else None,
            "loaned_to": private["loaned_to"] if private else None,
            "loaned_on": private["loaned_on"] if private else None,
        },
        "open_library": {"edition_key": b["ol_edition_key"], "cover": b["cover_url"]},
        "keys": {
            "sort_title": b["sort_title"],
            "title_key": b["title_key"],
            "natural_key": b["natural_key"],
        },
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "sources": [dict(s) for s in sources],
        "flags": [dict(f) for f in flags],
    }


def money(cents: int | None) -> str | None:
    return None if cents is None else f"${cents / 100:,.2f}"


def _credits_text(credits: list[dict]) -> str | None:
    if not credits:
        return None
    return "; ".join(
        c["name"] if c["role"] == "author" else f"{c['name']} ({c['role']})" for c in credits
    )


def flatten(d: dict) -> dict[str, str | None]:
    """The values a person edits, as display strings; used for before/after comparisons."""
    vol = d["volume"]
    return {
        "title": d["title"],
        "subtitle": d["subtitle"],
        "line": d["line"],
        "series": d["series"],
        "volume": None if vol is None else f"{vol:g}",
        "edition": d["edition"],
        "format": d["format"],
        "isbn": d["isbn13"],
        "publisher": d["publisher"],
        "year": None if d["year"] is None else str(d["year"]),
        "pages": None if d["pages"] is None else str(d["pages"]),
        "language": d["language"],
        "credits": _credits_text(d["credits"]),
        "tags": ", ".join(d["tags"]) or None,
        "contents": "; ".join(p["label"] + ("" if p["have"] else " (missing)") for p in d["parts"])
        or None,
        "copies": str(d["copies"]),
        "condition": d["condition"],
        "shelf": d["shelf"],
        "acquired": d["acquired"],
        "on website": "yes" if d["public"] and not d["removed"] else "no",
        "removed": d["removed"],
        "price paid": money(d["private"]["price_cents"]),
        "estimated value": money(d["private"]["value_cents"]),
        "notes": d["private"]["notes"],
        "loaned to": d["private"]["loaned_to"],
        "loaned on": d["private"]["loaned_on"],
        "cover": d["open_library"]["cover"],
        "Open Library key": d["open_library"]["edition_key"],
    }


SECTIONS = {
    "Book": [
        "title",
        "subtitle",
        "line",
        "series",
        "volume",
        "credits",
        "edition",
        "format",
        "isbn",
        "publisher",
        "year",
        "pages",
        "language",
        "tags",
    ],
    "Your copies": ["copies", "condition", "shelf", "acquired", "on website", "removed"],
    "Private (never published)": [
        "price paid",
        "estimated value",
        "notes",
        "loaned to",
        "loaned on",
    ],
    "Open Library": ["Open Library key", "cover"],
}


def format_details(d: dict) -> str:
    flat = flatten(d)
    if d["isbn10"]:
        flat["isbn"] = f"{d['isbn13']}  (ISBN-10 {d['isbn10']})"
    lines = [f"Book {d['id']}: {d['title']}"]
    for heading, keys in SECTIONS.items():
        lines.append(f"\n{heading}")
        lines += [f"  {k:<17}{flat[k] if flat[k] is not None else '-'}" for k in keys]
        if heading == "Book" and d["parts"]:
            lines.append("\nContents (numbers for --remove-part, --missing-part, --found-part)")
            lines += [
                f"  {n:<3}{p['kind']:<10}{p['label']}" + ("" if p["have"] else "   [missing]")
                for n, p in enumerate(d["parts"], start=1)
            ]
    lines.append("\nRecord")
    lines.append(f"  {'added':<17}{d['created_at']}")
    lines.append(f"  {'changed':<17}{d['updated_at']}")
    lines.append(f"  {'natural key':<17}{d['keys']['natural_key']}")
    for s in d["sources"]:
        lines.append(
            f"  {'imported from':<17}{s['source']} item {s['source_key']} (import run {s['first_seen_run']})"
        )
    if d["flags"]:
        lines.append("\nReview flags")
        for f in d["flags"]:
            state = f"resolved as {f['resolution']}" if f["resolved_at"] else "open"
            lines.append(f"  {f['flag_id']:<4} {f['reason']}: {f['details']}  [{state}]")
        if any(not f["resolved_at"] for f in d["flags"]):
            lines.append(
                "  Close one with: bookshelf review --resolve <number> ignored|distinct|merged"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------- changing a book

BOOK_COLUMNS = {  # option name -> books column
    "title": "title",
    "subtitle": "subtitle",
    "isbn": "isbn13",
    "publisher": "publisher",
    "year": "pub_year",
    "edition": "edition",
    "pages": "pages",
    "format": "format",
    "language": "language",
    "volume": "series_index",
    "copies": "copies",
    "shelf": "shelf",
    "condition": "condition",
    "acquired": "acquired_on",
    "cover": "cover_url",
    "ol-key": "ol_edition_key",
}
PRIVATE_COLUMNS = {
    "price": "purchase_price_cents",
    "value": "estimated_value_cents",
    "notes": "notes",
    "loaned-to": "loaned_to",
    "loaned-on": "loaned_on",
}
CLEARABLE = sorted(
    (set(BOOK_COLUMNS) - {"title", "copies"})
    | set(PRIVATE_COLUMNS)
    | {"line", "series", "loan", "authors", "tags", "parts"}
)


@dataclass
class Edit:
    set_book: dict[str, object] = field(default_factory=dict)  # option name -> new value
    set_private: dict[str, object] = field(default_factory=dict)
    line: str | None = None
    series: str | None = None
    trim_title: str | None = None  # a prefix to cut off the title, e.g. "Call of Cthulhu:"
    clear: list[str] = field(default_factory=list)
    credits: list[Credit] | None = None  # replaces all credits when given
    add_tags: list[str] = field(default_factory=list)
    remove_tags: list[str] = field(default_factory=list)
    # a set's contents; numbers are the positions `show` lists before the edit
    add_parts: list[Part] = field(default_factory=list)
    remove_parts: list[int] = field(default_factory=list)
    missing_parts: list[int] = field(default_factory=list)
    found_parts: list[int] = field(default_factory=list)
    remove_on: str | None = None
    restore: bool = False

    def is_empty(self) -> bool:
        return not (
            self.set_book
            or self.set_private
            or self.line
            or self.series
            or self.trim_title
            or self.clear
            or self.credits is not None
            or self.add_tags
            or self.remove_tags
            or self.add_parts
            or self.remove_parts
            or self.missing_parts
            or self.found_parts
            or self.remove_on
            or self.restore
        )


def _check_date(label: str, value: str) -> str:
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"{label} must be a date like 2026-11-17, not {value!r}") from None


# what may sit between a prefix and the rest of the title: "Call of Cthulhu: Arkham"
SEPARATORS = r"[\s:;,\-\u2013\u2014]*"


def trim_prefix(title: str, prefix: str) -> str:
    """ "Call of Cthulhu: Arkham Unveiled" minus "Call of Cthulhu" -> "Arkham Unveiled".

    Case-insensitive, and only whole words: "Call of Cthulhu" doesn't trim "Call of Cthulhuism".
    A title that doesn't start with the prefix, or would be left with nothing, comes back as is.
    """
    words = re.sub(rf"{SEPARATORS}$", "", prefix).split()  # "Call of Cthulhu:" = "Call of Cthulhu"
    if not words:
        return title
    pattern = r"\s+".join(re.escape(w) for w in words)
    hit = re.match(rf"\s*{pattern}(?:(?<=\W)|(?=\W|$)){SEPARATORS}", title, re.IGNORECASE)
    if not hit:
        return title
    rest = " ".join(title[hit.end() :].split())
    return rest if normalize_text(rest) else title


def apply_edit(conn: sqlite3.Connection, book_id: int, e: Edit) -> None:
    """Make the changes inside the caller's transaction. ValueError explains a refusal."""
    sets = dict(e.set_book)
    if "isbn" in sets:
        try:
            sets["isbn"] = to_isbn13(str(sets["isbn"]))
        except InvalidISBN as exc:
            raise ValueError(
                f"{sets['isbn']!r} isn't a valid ISBN ({exc.reason.replace('_', ' ')})"
            ) from None
        other = conn.execute(
            "SELECT book_id, title FROM books WHERE isbn13 = ? AND book_id <> ?",
            (sets["isbn"], book_id),
        ).fetchone()
        if other:
            raise ValueError(f"book {other[0]} ({other[1]}) already has ISBN {sets['isbn']}")
    if "acquired" in sets:
        sets["acquired"] = _check_date("--acquired", str(sets["acquired"]))
    if "title" in sets and not normalize_text(str(sets["title"])):
        raise ValueError("the title needs at least one letter or digit")
    if e.trim_title:
        if "title" in sets:
            raise ValueError("give either --title or --trim-title, not both")
        stored = conn.execute("SELECT title FROM books WHERE book_id = ?", (book_id,)).fetchone()[0]
        trimmed = trim_prefix(stored, e.trim_title)
        if trimmed != stored:
            sets["title"] = trimmed

    has_series = conn.execute(
        "SELECT series_id FROM books WHERE book_id = ?", (book_id,)
    ).fetchone()[0]
    series_after = bool(e.series) or (has_series is not None and "series" not in e.clear)
    if "volume" in sets and not series_after:
        raise ValueError("a volume number needs a series; give --series too")

    # Clears first, then sets: "--clear series --series X" moves the book, and a value you
    # type is never silently discarded by a clear in the same command.
    columns: dict[str, object] = {}
    for name in e.clear:
        if name == "series":
            columns.update(series_id=None, series_index=None)
        elif name == "line":
            columns["line_id"] = None
        elif name in BOOK_COLUMNS:
            columns[BOOK_COLUMNS[name]] = None
    columns.update({BOOK_COLUMNS[k]: v for k, v in sets.items()})
    if e.series:
        columns["series_id"] = get_or_create_series(conn, e.series)
    if e.line:
        columns["line_id"] = get_or_create_line(conn, e.line)
    if e.remove_on:
        columns["removed_on"] = _check_date("--remove", e.remove_on)
    if e.restore:
        columns["removed_on"] = None
    if columns:
        conn.execute(
            f"UPDATE books SET {', '.join(f'{c} = ?' for c in columns)} WHERE book_id = ?",
            (*columns.values(), book_id),
        )

    private: dict[str, object] = {}
    for name in e.clear:
        if name == "loan":
            private.update(loaned_to=None, loaned_on=None)
        elif name in PRIVATE_COLUMNS:
            private[PRIVATE_COLUMNS[name]] = None
    private.update({PRIVATE_COLUMNS[k]: v for k, v in e.set_private.items()})
    if "loaned-on" in e.set_private:
        private["loaned_on"] = _check_date("--loaned-on", str(e.set_private["loaned-on"]))
    if private:
        # Check the loan rule before the database does, so the message says what to do.
        stored = conn.execute(
            "SELECT loaned_to, loaned_on FROM book_private WHERE book_id = ?", (book_id,)
        ).fetchone()
        loaned_to = private.get("loaned_to", stored[0] if stored else None)
        loaned_on = private.get("loaned_on", stored[1] if stored else None)
        if loaned_on and not loaned_to:
            raise ValueError("a loan date needs a borrower; give --loaned-to too")
        conn.execute(
            "INSERT INTO book_private (book_id) VALUES (?) ON CONFLICT DO NOTHING", (book_id,)
        )
        conn.execute(
            f"UPDATE book_private SET {', '.join(f'{c} = ?' for c in private)} WHERE book_id = ?",
            (*private.values(), book_id),
        )

    if e.credits is not None or "authors" in e.clear:
        conn.execute("DELETE FROM book_authors WHERE book_id = ?", (book_id,))
        _add_credits(conn, book_id, e.credits or [])
    if "tags" in e.clear:
        conn.execute("DELETE FROM book_tags WHERE book_id = ?", (book_id,))
    _add_tags(conn, book_id, e.add_tags)
    for tag in e.remove_tags:
        conn.execute(
            "DELETE FROM book_tags WHERE book_id = ? AND tag_id = "
            "(SELECT tag_id FROM tags WHERE name_key = ?)",
            (book_id, normalize_text(tag)),
        )
    _edit_parts(conn, book_id, e)
    refresh_keys(conn, book_id)


def _edit_parts(conn: sqlite3.Connection, book_id: int, e: Edit) -> None:
    if not (
        e.add_parts or e.remove_parts or e.missing_parts or e.found_parts or "parts" in e.clear
    ):
        return
    parts = [] if "parts" in e.clear else read_parts(conn, book_id)
    for label, numbers in (
        ("--remove-part", e.remove_parts),
        ("--missing-part", e.missing_parts),
        ("--found-part", e.found_parts),
    ):
        for n in numbers:
            if not 1 <= n <= len(parts):
                listed = f"1 to {len(parts)}" if parts else "none yet"
                raise ValueError(f"{label} {n}: this book's parts are numbered {listed}")
    for n in e.missing_parts:
        parts[n - 1].have = False
    for n in e.found_parts:
        parts[n - 1].have = True
    gone = set(e.remove_parts)
    parts = [p for n, p in enumerate(parts, start=1) if n not in gone]
    write_parts(conn, book_id, parts + e.add_parts)


def changes(before: dict[str, str | None], after: dict[str, str | None]) -> list[str]:
    return [
        f"  {k}: {before[k] if before[k] is not None else '(empty)'}  ->  {after[k] if after[k] is not None else '(empty)'}"
        for k in before
        if before[k] != after[k]
    ]


# ---------------------------------------------------------------- choosing many books


def parse_ids(text: str) -> set[int]:
    """ "3,5,9-12" -> {3, 5, 9, 10, 11, 12}."""
    ids: set[int] = set()
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        hit = re.fullmatch(r"#?(\d+)(?:\s*-\s*#?(\d+))?", part)
        if not hit:
            raise ValueError(f"{part!r} isn't a book number or a range like 9-12")
        low, high = int(hit.group(1)), int(hit.group(2) or hit.group(1))
        if high < low:
            raise ValueError(f"the range {part!r} runs backwards")
        if high - low > 100_000:
            raise ValueError(f"the range {part!r} is too long")
        ids.update(range(low, high + 1))
    return ids


@dataclass
class Selection:
    """Which books edit-many changes. Every filter given must match (they combine with AND)."""

    title_has: str | None = None  # words appearing together in the title
    match: str | None = None  # the same rules as `bookshelf search`
    in_line: str | None = None
    in_series: str | None = None
    has_tags: list[str] = field(default_factory=list)
    from_publisher: str | None = None
    no_isbn: bool = False
    ids: set[int] | None = None
    except_ids: set[int] = field(default_factory=set)
    everything: bool = False
    include_removed: bool = False

    def is_empty(self) -> bool:
        return not (
            self.title_has
            or self.match
            or self.in_line
            or self.in_series
            or self.has_tags
            or self.from_publisher
            or self.no_isbn
            or self.ids is not None
            or self.everything
        )


def _same(a: str | None, b: str) -> bool:
    return a is not None and normalize_text(a) == normalize_text(b)


def select_books(conn: sqlite3.Connection, sel: Selection) -> list[int]:
    """The numbers of the books matching every filter in `sel`, in order."""
    if sel.is_empty():
        raise ValueError("choose some books first (or use --all to change every book)")
    tags: dict[int, set[str]] = {}
    for book_id, key in conn.execute(
        "SELECT bt.book_id, t.name_key FROM book_tags bt JOIN tags t USING (tag_id)"
    ):
        tags.setdefault(book_id, set()).add(key)
    matched: set[int] | None = None
    if sel.match:
        result = search(public_books(conn, include_hidden=True), sel.match)
        if result.mode in ("empty", "bad-isbn"):
            raise ValueError(f"--match {sel.match!r} isn't something search can look for")
        matched = {b["id"] for b in result.books}
    phrase = f" {normalize_text(sel.title_has)} " if sel.title_has else None
    if phrase is not None and not phrase.strip():
        raise ValueError("--title-has needs at least one letter or digit")
    wanted_tags = {normalize_text(t) for t in sel.has_tags}

    chosen = []
    for book_id, title, line, series, publisher, isbn, removed in conn.execute(
        "SELECT b.book_id, b.title, pl.name, s.name, b.publisher, b.isbn13, b.removed_on "
        "FROM books b LEFT JOIN series s USING (series_id) "
        "LEFT JOIN product_lines pl USING (line_id) ORDER BY b.book_id"
    ):
        if removed and not sel.include_removed:
            continue
        if sel.ids is not None and book_id not in sel.ids:
            continue
        if book_id in sel.except_ids:
            continue
        if phrase and phrase not in f" {normalize_text(title)} ":
            continue
        if matched is not None and book_id not in matched:
            continue
        if sel.in_line and not _same(line, sel.in_line):
            continue
        if sel.in_series and not _same(series, sel.in_series):
            continue
        if not wanted_tags <= tags.get(book_id, set()):
            continue
        if sel.from_publisher and not _same(publisher, sel.from_publisher):
            continue
        if sel.no_isbn and isbn:
            continue
        chosen.append(book_id)
    return chosen
