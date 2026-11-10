"""Inserting books with all their computed keys. Used by the seed now, by `add` and import later."""

import sqlite3
from dataclasses import dataclass, field

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
    pages: int | None = None
    format: str | None = None
    language: str | None = None
    series: str | None = None
    series_index: float | None = None
    copies: int = 1
    shelf: str | None = None
    condition: str | None = None
    acquired_on: str | None = None
    is_public: bool = True
    tags: list[str] = field(default_factory=list)
    # private, stored in book_private
    purchase_price_cents: int | None = None
    notes: str | None = None
    loaned_to: str | None = None
    loaned_on: str | None = None


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


def add_book(conn: sqlite3.Connection, book: NewBook) -> int:
    """Insert one book and everything hanging off it. The caller owns the transaction."""
    isbn13 = to_isbn13(book.isbn) if book.isbn else None
    series_id = get_or_create_series(conn, book.series) if book.series else None
    row = conn.execute(
        """
        INSERT INTO books (
            title, subtitle, sort_title, title_key, natural_key, isbn13, publisher, pub_year,
            pages, format, language, series_id, series_index, copies, shelf, condition,
            acquired_on, is_public
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING book_id
        """,
        (
            " ".join(book.title.split()),
            book.subtitle,
            sort_title(book.title),
            title_key(book.title),
            natural_key(book.title, _first_author_sort_name(book.credits), book.pub_year),
            isbn13,
            book.publisher,
            book.pub_year,
            book.pages,
            book.format,
            book.language,
            series_id,
            book.series_index,
            book.copies,
            book.shelf,
            book.condition,
            book.acquired_on,
            int(book.is_public),
        ),
    ).fetchone()
    book_id = row[0]

    for position, credit in enumerate(book.credits, start=1):
        conn.execute(
            "INSERT INTO book_authors (book_id, author_id, role, position) VALUES (?, ?, ?, ?)",
            (book_id, get_or_create_author(conn, credit.name), credit.role, position),
        )
    for tag in book.tags:
        conn.execute(
            "INSERT INTO book_tags (book_id, tag_id) VALUES (?, ?)",
            (book_id, get_or_create_tag(conn, tag)),
        )
    private = (book.purchase_price_cents, book.notes, book.loaned_to, book.loaned_on)
    if any(v is not None for v in private):
        conn.execute(
            "INSERT INTO book_private (book_id, purchase_price_cents, notes, loaned_to, loaned_on) "
            "VALUES (?, ?, ?, ?, ?)",
            (book_id, *private),
        )
    return book_id
