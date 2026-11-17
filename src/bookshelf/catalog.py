"""Writing books with all their computed keys. Used by the seed, the importer, and later `add`."""

import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from bookshelf.isbn import to_isbn13
from bookshelf.normalize import (
    author_match_key,
    natural_key,
    normalize_text,
    parse_person_name,
    sort_title,
    title_key,
)


@dataclass
class Credit:
    name: str  # as written: "Ursula K. Le Guin" or "Le Guin, Ursula K."
    role: str = "author"


@dataclass
class NewBook:
    title: str
    credits: list[Credit] = field(default_factory=list)  # in credited order
    subtitle: str | None = None
    isbn: str | None = None  # any written form; stored as ISBN-13
    publisher: str | None = None
    pub_year: int | None = None
    edition: str | None = None
    pages: int | None = None
    format: str | None = None
    language: str | None = None
    series: str | None = None
    series_index: float | None = None
    copies: int = 1
    shelf: str | None = None
    condition: str | None = None
    acquired_on: str | None = None
    ol_edition_key: str | None = None
    cover_url: str | None = None
    is_public: bool = True
    tags: list[str] = field(default_factory=list)
    # private, stored in book_private
    purchase_price_cents: int | None = None
    estimated_value_cents: int | None = None
    notes: str | None = None
    loaned_to: str | None = None
    loaned_on: str | None = None


# books columns copied straight from NewBook attributes of the same name
PLAIN_COLUMNS = (
    "subtitle",
    "publisher",
    "pub_year",
    "edition",
    "pages",
    "format",
    "language",
    "series_index",
    "copies",
    "shelf",
    "condition",
    "acquired_on",
    "ol_edition_key",
    "cover_url",
)
PRIVATE_COLUMNS = (
    "purchase_price_cents",
    "estimated_value_cents",
    "notes",
    "loaned_to",
    "loaned_on",
)


def get_or_create_author(conn: sqlite3.Connection, raw_name: str) -> int:
    name = parse_person_name(raw_name)
    key = author_match_key(name.sort_name)
    conn.execute(
        "INSERT INTO authors (display_name, sort_name, match_key) VALUES (?, ?, ?) "
        "ON CONFLICT (match_key) DO NOTHING",
        (name.display_name, name.sort_name, key),
    )
    return conn.execute("SELECT author_id FROM authors WHERE match_key = ?", (key,)).fetchone()[0]


def get_or_create_series(conn: sqlite3.Connection, name: str) -> int:
    key = title_key(name)
    conn.execute(
        "INSERT INTO series (name, name_key) VALUES (?, ?) ON CONFLICT (name_key) DO NOTHING",
        (" ".join(name.split()), key),
    )
    return conn.execute("SELECT series_id FROM series WHERE name_key = ?", (key,)).fetchone()[0]


def get_or_create_tag(conn: sqlite3.Connection, name: str) -> int:
    key = normalize_text(name)
    if not key:
        raise ValueError(f"tag has no letters or digits: {name!r}")
    conn.execute(
        "INSERT INTO tags (name, name_key) VALUES (?, ?) ON CONFLICT (name_key) DO NOTHING",
        (" ".join(name.split()), key),
    )
    return conn.execute("SELECT tag_id FROM tags WHERE name_key = ?", (key,)).fetchone()[0]


def _first_author_sort_name(credits: list[Credit]) -> str | None:
    """The first credit with role 'author', else the first credit of any role, else None."""
    chosen = next((c for c in credits if c.role == "author"), credits[0] if credits else None)
    return parse_person_name(chosen.name).sort_name if chosen else None


def book_natural_key(
    title: str, series: str | None, first_author_sort_name: str | None, pub_year: int | None
) -> str:
    """The series name is part of a book's identity: "DND 3.5" + "Monster Manual" is not
    "Pathfinder" + "Monster Manual", and many series reuse titles like "Core Rulebook"."""
    full_title = f"{series} {title}" if series else title
    return natural_key(full_title, first_author_sort_name, pub_year)


def find_by_natural_key(conn: sqlite3.Connection, book: NewBook) -> list[int]:
    key = book_natural_key(
        book.title, book.series, _first_author_sort_name(book.credits), book.pub_year
    )
    return [r[0] for r in conn.execute("SELECT book_id FROM books WHERE natural_key = ?", (key,))]


def _add_credits(conn: sqlite3.Connection, book_id: int, credits: list[Credit]) -> None:
    for position, credit in enumerate(credits, start=1):
        conn.execute(
            "INSERT INTO book_authors (book_id, author_id, role, position) VALUES (?, ?, ?, ?) "
            "ON CONFLICT DO NOTHING",
            (book_id, get_or_create_author(conn, credit.name), credit.role, position),
        )


def _add_tags(conn: sqlite3.Connection, book_id: int, tags: list[str]) -> None:
    for tag in tags:
        conn.execute(
            "INSERT INTO book_tags (book_id, tag_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
            (book_id, get_or_create_tag(conn, tag)),
        )


def refresh_keys(conn: sqlite3.Connection, book_id: int) -> None:
    """Recompute sort_title, title_key and natural_key from the row as it stands now."""
    title, series, year = conn.execute(
        "SELECT b.title, s.name, b.pub_year FROM books b "
        "LEFT JOIN series s USING (series_id) WHERE b.book_id = ?",
        (book_id,),
    ).fetchone()
    first = conn.execute(
        "SELECT a.sort_name FROM book_authors ba JOIN authors a USING (author_id) "
        "WHERE ba.book_id = ? ORDER BY ba.role <> 'author', ba.position LIMIT 1",
        (book_id,),
    ).fetchone()
    conn.execute(
        "UPDATE books SET sort_title = ?, title_key = ?, natural_key = ? WHERE book_id = ?",
        (
            sort_title(title),
            title_key(title),
            book_natural_key(title, series, first[0] if first else None, year),
            book_id,
        ),
    )


def add_book(conn: sqlite3.Connection, book: NewBook) -> int:
    """Insert one book and everything hanging off it. The caller owns the transaction."""
    isbn13 = to_isbn13(book.isbn) if book.isbn else None
    series_id = get_or_create_series(conn, book.series) if book.series else None
    columns = ["title", "isbn13", "series_id", "is_public", *PLAIN_COLUMNS]
    values = [
        " ".join(book.title.split()),
        isbn13,
        series_id,
        int(book.is_public),
        *(getattr(book, c) for c in PLAIN_COLUMNS),
    ]
    # Key columns get placeholders here and their real values from refresh_keys below,
    # so add and update compute keys in exactly one place.
    columns += ["sort_title", "title_key", "natural_key"]
    values += ["", "", ""]
    book_id = conn.execute(
        f"INSERT INTO books ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
        "RETURNING book_id",
        values,
    ).fetchone()[0]
    _add_credits(conn, book_id, book.credits)
    _add_tags(conn, book_id, book.tags)
    _write_private(conn, book_id, book, "overwrite")
    refresh_keys(conn, book_id)
    return book_id


def _write_private(
    conn: sqlite3.Connection, book_id: int, book: NewBook, mode: Literal["overwrite", "fill"]
) -> None:
    values = [getattr(book, c) for c in PRIVATE_COLUMNS]
    if all(v is None for v in values):
        return
    # overwrite: a new non-NULL value wins; fill: an existing non-NULL value wins
    pick = "coalesce(excluded.{c}, {c})" if mode == "overwrite" else "coalesce({c}, excluded.{c})"
    updates = ", ".join(f"{c} = " + pick.format(c=c) for c in PRIVATE_COLUMNS)
    conn.execute(
        f"INSERT INTO book_private (book_id, {', '.join(PRIVATE_COLUMNS)}) "
        f"VALUES (?, {', '.join('?' * len(PRIVATE_COLUMNS))}) "
        f"ON CONFLICT (book_id) DO UPDATE SET {updates}",
        (book_id, *values),
    )


def update_book(
    conn: sqlite3.Connection, book_id: int, book: NewBook, mode: Literal["overwrite", "fill"]
) -> None:
    """Merge `book` into an existing row.

    overwrite: every value `book` supplies replaces the stored one, and its credits replace the
               stored credits. Used when re-importing a book from the source it came from.
    fill:      only empty stored values are filled, and credits are added only if there are none.
               Used when an import matches a book that already exists by ISBN.
    A value `book` doesn't supply (None, or an empty credit list) never erases anything,
    so data added later, such as Open Library enrichment, survives a re-import.
    """
    supplied = {c: getattr(book, c) for c in PLAIN_COLUMNS if getattr(book, c) is not None}
    supplied["is_public"] = int(book.is_public)
    if book.isbn:
        supplied["isbn13"] = to_isbn13(book.isbn)
    if book.series:
        supplied["series_id"] = get_or_create_series(conn, book.series)
    if mode == "overwrite":
        supplied["title"] = " ".join(book.title.split())
        sets = [f"{c} = ?" for c in supplied]
    else:
        supplied.pop("copies", None)  # 1 is a default, not information
        supplied.pop("is_public", None)
        sets = [f"{c} = coalesce({c}, ?)" for c in supplied]
    if sets:
        conn.execute(
            f"UPDATE books SET {', '.join(sets)} WHERE book_id = ?", (*supplied.values(), book_id)
        )

    has_credits = conn.execute(
        "SELECT 1 FROM book_authors WHERE book_id = ?", (book_id,)
    ).fetchone()
    if book.credits and (mode == "overwrite" or not has_credits):
        conn.execute("DELETE FROM book_authors WHERE book_id = ?", (book_id,))
        _add_credits(conn, book_id, book.credits)
    _add_tags(conn, book_id, book.tags)
    _write_private(conn, book_id, book, mode)
    refresh_keys(conn, book_id)
