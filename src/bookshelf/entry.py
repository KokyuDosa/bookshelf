"""Helpers behind `bookshelf add` and `bookshelf enrich`."""

import sqlite3
from collections.abc import Callable

from bookshelf.catalog import Credit, NewBook, update_book
from bookshelf.normalize import normalize_text
from bookshelf.openlibrary import LookupFailed, OpenLibrary

LOOKUPS = {"format": ("formats", "format"), "condition": ("conditions", "condition")}


def lookup_code(conn: sqlite3.Connection, kind: str, value: str) -> str:
    """ "Box set", "box_set" or "BOX SET" -> "box_set". ValueError lists the allowed values."""
    table, column = LOOKUPS[kind]
    allowed = [r[0] for r in conn.execute(f"SELECT {column} FROM {table} ORDER BY sort_order")]
    code = normalize_text(value).replace(" ", "_")
    if code not in allowed:
        raise ValueError(f"unknown {kind} {value!r}; use one of: {', '.join(allowed)}")
    return code


def find_owned(conn: sqlite3.Connection, isbn13: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT b.book_id, b.title, b.copies, pl.name AS line, s.name AS series, b.series_index "
        "FROM active_books b LEFT JOIN series s USING (series_id) "
        "LEFT JOIN product_lines pl USING (line_id) WHERE b.isbn13 = ?",
        (isbn13,),
    ).fetchone()


# Columns enrichment may fill. Subtitles are left alone: imported titles often already
# contain them ("Libris Mortis: The Book of Undead").
ENRICHABLE = ("publisher", "pub_year", "pages", "cover_url", "ol_edition_key")


def enrich(
    conn: sqlite3.Connection,
    ol: OpenLibrary,
    limit: int | None = None,
    say: Callable[[str], None] = print,
) -> dict[str, int]:
    """Fill empty details of books that have an ISBN. Never overwrites a value already set."""
    empty = " OR ".join(f"{c} IS NULL" for c in ENRICHABLE)
    rows = conn.execute(
        f"SELECT book_id, title, isbn13, {', '.join(ENRICHABLE)} FROM active_books "
        f"WHERE isbn13 IS NOT NULL AND ({empty}) ORDER BY book_id"
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    counts = {"checked": 0, "filled": 0, "not_found": 0, "skipped": 0}
    for n, row in enumerate(rows, start=1):
        try:
            found = ol.lookup(row["isbn13"])
        except LookupFailed as exc:
            say(f"Stopped after {n - 1} of {len(rows)}: {exc}. Run enrich again to carry on.")
            break
        counts["checked"] += 1
        if found is None:
            counts["not_found"] += 1
            continue
        book = NewBook(
            title=row["title"],
            credits=[Credit(a) for a in found.authors],
            publisher=found.publisher,
            pub_year=found.pub_year,
            pages=found.pages,
            cover_url=found.cover_url,
            ol_edition_key=found.ol_edition_key,
        )
        try:
            with conn:
                update_book(conn, row["book_id"], book, "fill")
        except (sqlite3.IntegrityError, ValueError) as exc:
            # e.g. two of your editions map to one Open Library record (ol_edition_key is UNIQUE)
            counts["skipped"] += 1
            say(f"[{n}/{len(rows)}] {row['title']}: skipped ({exc})")
            continue
        after = conn.execute(
            f"SELECT {', '.join(ENRICHABLE)} FROM books WHERE book_id = ?", (row["book_id"],)
        ).fetchone()
        filled = [c for c in ENRICHABLE if row[c] is None and after[c] is not None]
        if filled:
            counts["filled"] += 1
            say(f"[{n}/{len(rows)}] {row['title']}: {', '.join(filled)}")
    return counts
