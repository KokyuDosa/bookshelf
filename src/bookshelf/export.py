"""The public view of the collection: what the website shows and what `search` matches.

Only the columns in PUBLIC_FIELDS ever leave the database. Nothing is read from book_private,
and books that are soft-deleted or marked not public are left out.
"""

import csv
import io
import json
import sqlite3
from pathlib import Path

from bookshelf.normalize import normalize_text

EXPORT_VERSION = 1
PUBLIC_FIELDS = (
    "id",
    "title",
    "subtitle",
    "line",
    "series",
    "volume",
    "authors",
    "edition",
    "format",
    "publisher",
    "year",
    "isbn",
    "copies",
    "tags",
    "cover",
    "key",
)

BOOKS_SQL = """
SELECT b.book_id, b.title, b.subtitle, pl.name AS line, s.name AS series, b.series_index, b.edition,
       f.label AS format, b.publisher, b.pub_year, b.isbn13, b.copies, b.cover_url,
       b.sort_title, b.updated_at
FROM active_books b
LEFT JOIN series s ON s.series_id = b.series_id
LEFT JOIN product_lines pl ON pl.line_id = b.line_id
LEFT JOIN formats f ON f.format = b.format
WHERE b.is_public = 1 OR :include_hidden
"""


def search_key(
    title: str,
    subtitle: str | None,
    line: str | None,
    series: str | None,
    volume: float | None,
    authors: list[str],
) -> str:
    """The text a search matches against: normalised title, subtitle, line, series, "vol N" and
    authors,
    so "happiness 7" and "happiness vol 7" both find volume 7.
    The website's search.js normalises typed text the same way (tests/fixtures holds the cases)."""
    vol = f"vol {volume:g}" if volume is not None else None
    return normalize_text(" ".join(p for p in (title, subtitle, line, series, vol, *authors) if p))


def _volume(index: float | None) -> int | float | None:
    if index is None:
        return None
    return int(index) if float(index).is_integer() else index


def public_books(conn: sqlite3.Connection, include_hidden: bool = False) -> list[dict]:
    """Every public book as a dict of PUBLIC_FIELDS, in a stable order.
    include_hidden adds books marked not public; only local search uses it."""
    credits: dict[int, list[str]] = {}
    for book_id, name in conn.execute(
        "SELECT ba.book_id, a.display_name FROM book_authors ba JOIN authors a USING (author_id) "
        "ORDER BY ba.book_id, ba.position"
    ):
        credits.setdefault(book_id, []).append(name)
    tags: dict[int, list[str]] = {}
    for book_id, name in conn.execute(
        "SELECT bt.book_id, t.name FROM book_tags bt JOIN tags t USING (tag_id) ORDER BY t.name_key"
    ):
        tags.setdefault(book_id, []).append(name)

    books = []
    for row in conn.execute(BOOKS_SQL + " ORDER BY b.book_id", {"include_hidden": include_hidden}):
        (
            book_id,
            title,
            subtitle,
            line,
            series,
            index,
            edition,
            fmt,
            publisher,
            year,
            isbn,
            copies,
            cover,
            _sort,
            _updated,
        ) = row
        authors = credits.get(book_id, [])
        book = {
            "id": book_id,
            "title": title,
            "subtitle": subtitle,
            "line": line,
            "series": series,
            "volume": _volume(index),
            "authors": authors,
            "edition": edition,
            "format": fmt,
            "publisher": publisher,
            "year": year,
            "isbn": isbn,
            "copies": copies,
            "tags": tags.get(book_id, []),
            "cover": cover,
            "key": search_key(title, subtitle, line, series, index, authors),
        }
        books.append({k: v for k, v in book.items() if v not in (None, [])})
    assert all(set(b) <= set(PUBLIC_FIELDS) for b in books)
    return books


def data_as_of(conn: sqlite3.Connection) -> str | None:
    """The latest change to any book, so an unchanged database exports byte-identical files."""
    return conn.execute("SELECT max(updated_at) FROM books").fetchone()[0]


def books_json(conn: sqlite3.Connection) -> str:
    payload = {
        "version": EXPORT_VERSION,
        "as_of": data_as_of(conn),
        "count": None,
        "books": public_books(conn),
    }
    payload["count"] = len(payload["books"])
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def books_csv(conn: sqlite3.Connection) -> str:
    """A spreadsheet-friendly list for friends, sorted by line, series, volume, then title."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "Line",
            "Title",
            "Subtitle",
            "Series",
            "Volume",
            "Authors",
            "Edition",
            "Format",
            "Publisher",
            "Year",
            "ISBN",
            "Copies",
            "Tags",
        ]
    )
    rows = public_books(conn)
    rows.sort(
        key=lambda b: (
            normalize_text(b.get("line", "")),
            normalize_text(b.get("series", "")),
            b.get("volume", 0),
            b["key"],
        )
    )
    for b in rows:
        writer.writerow(
            [
                b.get("line", ""),
                b["title"],
                b.get("subtitle", ""),
                b.get("series", ""),
                b.get("volume", ""),
                "; ".join(b.get("authors", [])),
                b.get("edition", ""),
                b.get("format", ""),
                b.get("publisher", ""),
                b.get("year", ""),
                b.get("isbn", ""),
                b["copies"],
                "; ".join(b.get("tags", [])),
            ]
        )
    return out.getvalue()


def write_export(conn: sqlite3.Connection, site_data: Path) -> dict[str, Path]:
    """Write books.json and books.csv into site_data. Returns the paths written."""
    site_data.mkdir(parents=True, exist_ok=True)
    files = {"books.json": books_json(conn), "books.csv": books_csv(conn)}
    paths = {}
    for name, text in files.items():
        path = site_data / name
        # utf-8-sig on the CSV so Excel shows accented names correctly
        encoding = "utf-8-sig" if name.endswith(".csv") else "utf-8"
        path.write_text(text, encoding=encoding, newline="")
        paths[name] = path
    return paths


def summarize_changes(old_json: str | None, new_json: str) -> dict[str, int]:
    """Added, changed and removed public books between two books.json files."""
    old = {b["id"]: b for b in json.loads(old_json)["books"]} if old_json else {}
    new = {b["id"]: b for b in json.loads(new_json)["books"]}
    return {
        "added": len(new.keys() - old.keys()),
        "removed": len(old.keys() - new.keys()),
        "changed": sum(1 for k in new.keys() & old.keys() if new[k] != old[k]),
        "total": len(new),
    }
