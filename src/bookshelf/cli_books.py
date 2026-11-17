"""The everyday commands: add, search, enrich, export, publish."""

import argparse
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from bookshelf import migrations
from bookshelf.catalog import Credit, NewBook, add_book, find_by_natural_key
from bookshelf.db import connect
from bookshelf.entry import enrich, find_owned, lookup_code
from bookshelf.export import public_books, write_export
from bookshelf.importers.mapping import normalize_edition, parse_money_cents
from bookshelf.isbn import InvalidISBN, to_isbn13
from bookshelf.openlibrary import LookupFailed, OpenLibrary
from bookshelf.paths import PROJECT_ROOT
from bookshelf.publish import PublishError, publish
from bookshelf.search import describe, search

SITE_DATA = PROJECT_ROOT / "site" / "data"


def fail(message: str, code: int = 1) -> int:
    print(message, file=sys.stderr)
    return code


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def ask(prompt: str) -> str:
    try:
        return input(f"{prompt}: ").strip()
    except EOFError:
        return ""


def confirm(question: str) -> bool:
    return ask(f"{question} [Y/n]").lower() in ("", "y", "yes")


def open_db(path: Path) -> sqlite3.Connection | None:
    """Connect only to an existing database whose schema is current."""
    if not path.exists():
        fail(f"{path} does not exist. Run 'bookshelf init' first.")
        return None
    conn = connect(path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    latest = migrations.discover()[-1][0]
    if version < latest:
        conn.close()
        fail(
            f"Your database is at schema version {version}; run 'bookshelf migrate' to reach {latest}."
        )
        return None
    return conn


def copies_text(n: int) -> str:
    return f"{n} {'copy' if n == 1 else 'copies'}"


# ---------------------------------------------------------------- add


def cmd_add(args: argparse.Namespace) -> int:
    if args.volume is not None and not args.series:
        return fail("--volume needs --series (the volume number is a position in a series).")
    conn = open_db(args.db)
    if conn is None:
        return 1
    with closing(conn), conn:
        return _add(conn, args)


def _add(conn: sqlite3.Connection, args: argparse.Namespace) -> int:
    isbn13 = None
    if args.isbn:
        try:
            isbn13 = to_isbn13(args.isbn)
        except InvalidISBN as exc:
            return fail(f"{args.isbn!r} isn't a valid ISBN ({exc.reason.replace('_', ' ')}).")
        owned = find_owned(conn, isbn13)
        if owned:
            label = f"{owned['series']}; {owned['title']}" if owned["series"] else owned["title"]
            if args.another_copy:
                conn.execute(
                    "UPDATE books SET copies = copies + 1 WHERE book_id = ?", (owned["book_id"],)
                )
                print(
                    f"Counted another copy: you now have {copies_text(owned['copies'] + 1)} of {label}."
                )
            else:
                print(f"Already in your collection: {label} ({copies_text(owned['copies'])}).")
                print("Bought another? Run the same command with --another-copy.")
            return 0

    found = None
    if isbn13 and not args.offline:
        try:
            found = OpenLibrary(conn).lookup(isbn13)
            if found is None:
                print("Open Library doesn't know this ISBN; enter the details yourself.")
        except LookupFailed as exc:
            print(f"{exc}. Enter the details yourself.")

    title = args.title or (found.title if found else None)
    authors = args.author or (found.authors if found else [])
    if not title and interactive():
        title = ask("Title")
        if not authors:
            authors = [
                a.strip() for a in ask("Authors, separated by ; (optional)").split(";") if a.strip()
            ]
    if not title:
        return fail("No title. Give one with --title, or an ISBN Open Library knows.")

    try:
        book = NewBook(
            title=title,
            subtitle=args.subtitle or (found.subtitle if found else None),
            credits=[Credit(a) for a in authors],
            isbn=isbn13,
            publisher=args.publisher or (found.publisher if found else None),
            pub_year=args.year or (found.pub_year if found else None),
            pages=args.pages or (found.pages if found else None),
            edition=normalize_edition(args.edition) if args.edition else None,
            format=lookup_code(conn, "format", args.format) if args.format else None,
            condition=lookup_code(conn, "condition", args.condition) if args.condition else None,
            series=args.series,
            series_index=args.volume,
            copies=args.copies,
            shelf=args.shelf,
            is_public=not args.hidden,
            tags=args.tag or [],
            estimated_value_cents=parse_money_cents(args.value) if args.value else None,
            cover_url=found.cover_url if found else None,
            ol_edition_key=found.ol_edition_key if found else None,
        )
    except ValueError as exc:
        return fail(str(exc))
    if (
        book.ol_edition_key
        and conn.execute(
            "SELECT 1 FROM books WHERE ol_edition_key = ?", (book.ol_edition_key,)
        ).fetchone()
    ):
        book.ol_edition_key = None  # another of your books already holds that Open Library record

    preview = {
        "title": book.title,
        "subtitle": book.subtitle,
        "series": book.series,
        "volume": book.series_index,
        "authors": [c.name for c in book.credits],
        "edition": book.edition,
        "format": book.format,
        "year": book.pub_year,
        "copies": book.copies,
    }
    print(f"  {describe({k: v for k, v in preview.items() if v not in (None, [])})}")
    if isbn13:
        print(f"  ISBN {isbn13}" + ("" if book.is_public else "  (hidden from the website)"))
    duplicates = find_by_natural_key(conn, book)
    if duplicates:
        print(f"  Careful: this looks like book #{duplicates[0]}, already in your collection.")
    if interactive() and not args.yes and not confirm("Add it?"):
        print("Not added.")
        return 1

    book_id = add_book(conn, book)
    if duplicates:
        conn.execute(
            "INSERT INTO review_flags (book_id, candidate_book_id, reason, details) VALUES (?, ?, ?, ?)",
            (
                book_id,
                duplicates[0],
                "possible_duplicate",
                f"added by hand; resembles book {duplicates[0]}",
            ),
        )
    print(f"Added as book #{book_id}. Run 'bookshelf publish' to put it on the website.")
    return 0


# ---------------------------------------------------------------- search


def cmd_search(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if conn is None:
        return 1
    with closing(conn), conn:
        result = search(public_books(conn, include_hidden=True), " ".join(args.query))
    if result.mode == "empty":
        return fail("Give some words to search for: bookshelf search hobbit")
    if result.mode == "bad-isbn":
        return fail("That isn't a valid ISBN: the check digit doesn't match.", 2)
    if not result.books:
        print(
            "Not in the collection." + (f" No book has ISBN {result.isbn}." if result.isbn else "")
        )
        return 1
    print(
        f"In the collection ({len(result.books)}):"
        if len(result.books) > 1
        else "In the collection:"
    )
    for book in result.books[: args.limit]:
        print(f"  {describe(book)}")
    if len(result.books) > args.limit:
        print(f"  … and {len(result.books) - args.limit} more (use --limit)")
    return 0


# ---------------------------------------------------------------- enrich, export, publish


def cmd_enrich(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if conn is None:
        return 1
    with closing(conn), conn:
        ol = OpenLibrary(conn)
        counts = enrich(conn, ol, limit=args.limit)
    print(
        f"Checked {counts['checked']} books: {counts['filled']} filled in, "
        f"{counts['not_found']} unknown to Open Library, {counts['skipped']} skipped. "
        f"{ol.requests} network requests; the rest came from the cache."
    )
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if conn is None:
        return 1
    with closing(conn), conn:
        paths = write_export(conn, args.out)
    for path in paths.values():
        print(f"Wrote {path} ({path.stat().st_size / 1024:,.0f} KB)")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if conn is None:
        return 1
    conn.close()
    ask_first = interactive() and not args.yes
    try:
        publish(
            args.db,
            PROJECT_ROOT,
            run_tests=not args.no_tests,
            push=not args.no_push,
            confirm=confirm if ask_first else (lambda _: True),
        )
    except PublishError as exc:
        return fail(f"Publish stopped: {exc}")
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("add", help="add a book by ISBN, or by hand")
    p.add_argument("isbn", nargs="?", help="ISBN-10 or ISBN-13, hyphens allowed")
    p.add_argument("--title")
    p.add_argument("--subtitle")
    p.add_argument("--author", action="append", help="repeat for each author, in credit order")
    p.add_argument("--series", help="series or game line, e.g. 'One Piece' or 'DND 3.5'")
    p.add_argument("--volume", type=float, help="number in the series, e.g. 12 (needs --series)")
    p.add_argument("--edition", help="e.g. 2nd, Omnibus, Gold Edition")
    p.add_argument(
        "--format",
        help="hardcover, trade paperback, mass market, paperback, box set, ebook, audiobook, other",
    )
    p.add_argument("--condition", help="mint, like new, excellent, very good, good, fair, poor")
    p.add_argument("--publisher")
    p.add_argument("--year", type=int)
    p.add_argument("--pages", type=int)
    p.add_argument("--copies", type=int, default=1)
    p.add_argument("--shelf", help="where it lives; never published")
    p.add_argument("--tag", action="append", help="genre or label; repeat for several")
    p.add_argument("--value", help="estimated value, e.g. 45.00; private")
    p.add_argument("--hidden", action="store_true", help="keep this book off the website")
    p.add_argument(
        "--another-copy", action="store_true", help="if you own this ISBN, count one more copy"
    )
    p.add_argument("--offline", action="store_true", help="don't ask Open Library")
    p.add_argument("--yes", "-y", action="store_true", help="add without asking to confirm")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("search", help="do I own this? title, series, author or ISBN")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser(
        "enrich", help="fill missing years, pages, publishers and covers from Open Library"
    )
    p.add_argument("--limit", type=int, help="stop after this many books")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("export", help="write the website's data files without publishing")
    p.add_argument("--out", type=Path, default=SITE_DATA, help=f"(default: {SITE_DATA})")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("publish", help="export, test, commit and push the website")
    p.add_argument("--yes", "-y", action="store_true", help="don't ask before committing")
    p.add_argument("--no-tests", action="store_true", help="skip the test run")
    p.add_argument("--no-push", action="store_true", help="commit but don't push")
    p.set_defaults(func=cmd_publish)
