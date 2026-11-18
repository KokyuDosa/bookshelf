"""The everyday commands: add, show, edit, search, enrich, export, publish."""

import argparse
import datetime as dt
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

from bookshelf import migrations
from bookshelf.catalog import Credit, NewBook, add_book, find_by_natural_key, rekey_all
from bookshelf.db import connect
from bookshelf.editing import (
    CLEARABLE,
    Edit,
    apply_edit,
    changes,
    details,
    flatten,
    format_details,
    resolve,
)
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
    credits = args.credits or [Credit(a) for a in (found.authors if found else [])]
    if not title and interactive():
        title = ask("Title")
        if not credits:
            names = ask("Authors, separated by ; (optional)").split(";")
            credits = [Credit(a.strip()) for a in names if a.strip()]
    if not title:
        return fail("No title. Give one with --title, or an ISBN Open Library knows.")

    try:
        book = NewBook(
            title=title,
            subtitle=args.subtitle or (found.subtitle if found else None),
            credits=credits,
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


# ---------------------------------------------------------------- show and edit


def pick(conn: sqlite3.Connection, ref: str) -> int | None:
    """The book a reference means, or None after explaining why there isn't exactly one."""
    try:
        found = resolve(conn, ref)
    except ValueError as exc:
        fail(str(exc))
        return None
    if found.book_id is not None:
        return found.book_id
    if found.candidates:
        fail(f"{len(found.candidates)} books match {ref!r}; use the number of the one you mean:")
        for book_id, text in found.candidates[:15]:
            print(f"  {book_id:>5}  {text}", file=sys.stderr)
    else:
        fail(f"No book matches {ref!r}.")
    return None


def cmd_show(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if conn is None:
        return 1
    with closing(conn):
        book_id = pick(conn, " ".join(args.book))
        if book_id is None:
            return 1
        d = details(conn, book_id)
    print(json.dumps(d, indent=2, ensure_ascii=False) if args.json else format_details(d))
    return 0


def build_edit(conn: sqlite3.Connection, args: argparse.Namespace) -> Edit:
    """Command-line options -> an Edit. ValueError for values that can't be used."""
    e = Edit(
        series=args.series,
        clear=args.clear or [],
        credits=args.credits,
        add_tags=args.add_tag or [],
        remove_tags=args.remove_tag or [],
        remove_on=args.remove,
        restore=args.restore,
    )
    for name in (
        "title",
        "subtitle",
        "isbn",
        "publisher",
        "language",
        "shelf",
        "cover",
        "year",
        "pages",
        "copies",
        "volume",
        "acquired",
    ):
        value = getattr(args, name.replace("-", "_"))
        if value is not None:
            e.set_book[name] = value
    if args.ol_key is not None:
        e.set_book["ol-key"] = args.ol_key
    if args.edition is not None:
        e.set_book["edition"] = normalize_edition(args.edition)
    if args.format is not None:
        e.set_book["format"] = lookup_code(conn, "format", args.format)
    if args.condition is not None:
        e.set_book["condition"] = lookup_code(conn, "condition", args.condition)
    for name in ("price", "value"):
        if getattr(args, name) is not None:
            e.set_private[name] = parse_money_cents(getattr(args, name))
    for name in ("notes", "loaned_to", "loaned_on"):
        if getattr(args, name) is not None:
            e.set_private[name.replace("_", "-")] = getattr(args, name)
    if args.remove and args.restore:
        raise ValueError("--remove and --restore can't be used together")
    return e


def cmd_edit(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if conn is None:
        return 1
    with closing(conn):
        book_id = pick(conn, args.book)
        if book_id is None:
            return 1
        try:
            edit = build_edit(conn, args)
        except ValueError as exc:
            return fail(str(exc))
        if edit.is_empty():
            return fail(
                "Nothing to change. Try options like --isbn, --title or --clear isbn "
                "(bookshelf edit --help lists them all)."
            )
        before = flatten(details(conn, book_id))
        try:
            apply_edit(conn, book_id, edit)
        except (ValueError, sqlite3.IntegrityError) as exc:
            conn.rollback()
            return fail(f"Not changed: {exc}")
        after = flatten(details(conn, book_id))
        diff = changes(before, after)
        if not diff:
            conn.rollback()
            print(f"No change: book {book_id} already has those values.")
            return 0
        print(f"Book {book_id}: {after['title']}")
        print("\n".join(diff))
        if interactive() and not args.yes and not confirm("Save these changes?"):
            conn.rollback()
            print("Nothing changed.")
            return 1
        conn.commit()
    print("Saved. Run 'bookshelf publish' to update the website.")
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
        print(f"  {book['id']:>5}  {describe(book)}")
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


def cmd_rekey(args: argparse.Namespace) -> int:
    conn = open_db(args.db)
    if conn is None:
        return 1
    with closing(conn), conn:
        total = conn.execute("SELECT count(*) FROM books").fetchone()[0]
        changed = rekey_all(conn)
    print(f"Recomputed the keys of {total} books; {changed} changed.")
    if changed:
        print("Run 'bookshelf publish' so the website's search picks up the change.")
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


def add_credit_options(p: argparse.ArgumentParser, verb: str) -> None:
    """--author, --editor, --translator, --illustrator: kept in the order you type them."""
    for flag, role in (
        ("--author", "author"),
        ("--editor", "editor"),
        ("--translator", "translator"),
        ("--illustrator", "illustrator"),
    ):
        p.add_argument(
            flag,
            dest="credits",
            action="append",
            metavar="NAME",
            type=lambda name, role=role: Credit(name.strip(), role),
            help=f"{verb}; repeat for several people",
        )


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("add", help="add a book by ISBN, or by hand")
    p.add_argument("isbn", nargs="?", help="ISBN-10 or ISBN-13, hyphens allowed")
    p.add_argument("--title")
    p.add_argument("--subtitle")
    add_credit_options(p, "credit a person")
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

    p = sub.add_parser("show", help="every stored value for one book, private ones included")
    p.add_argument("book", nargs="+", help="book number, ISBN, or words from the title")
    p.add_argument("--json", action="store_true", help="print as JSON")
    p.set_defaults(func=cmd_show)

    today = dt.date.today().isoformat()
    p = sub.add_parser("edit", help="change or clear any value of one book")
    p.add_argument("book", help="book number, ISBN, or words from the title (quote several words)")
    for name in ("title", "subtitle", "isbn", "publisher", "edition", "language", "shelf", "notes"):
        p.add_argument(f"--{name}")
    p.add_argument("--series", help="move the book into this series (created if new)")
    p.add_argument("--volume", type=float, help="number in the series")
    p.add_argument(
        "--format",
        help="hardcover, trade paperback, mass market, paperback, box set, ebook, audiobook, other",
    )
    p.add_argument("--condition", help="mint, like new, excellent, very good, good, fair, poor")
    p.add_argument("--year", type=int)
    p.add_argument("--pages", type=int)
    p.add_argument("--copies", type=int)
    p.add_argument("--acquired", metavar="DATE", help="e.g. 2024-06-01")
    p.add_argument("--price", help="what you paid, e.g. 12.50; private")
    p.add_argument("--value", help="estimated value, e.g. 45.00; private")
    p.add_argument("--loaned-to", metavar="NAME")
    p.add_argument("--loaned-on", metavar="DATE")
    p.add_argument("--cover", metavar="URL")
    p.add_argument("--ol-key", metavar="KEY", help="Open Library edition key, e.g. OL7353617M")
    add_credit_options(p, "replace all credits with these people")
    p.add_argument("--add-tag", action="append", metavar="TAG")
    p.add_argument("--remove-tag", action="append", metavar="TAG")
    p.add_argument(
        "--clear",
        action="append",
        choices=CLEARABLE,
        metavar="FIELD",
        help=f"empty a field; repeat for several. One of: {', '.join(CLEARABLE)}",
    )
    p.add_argument(
        "--remove",
        nargs="?",
        const=today,
        metavar="DATE",
        help="mark as gone (given away, sold); kept in the database, off the website",
    )
    p.add_argument("--restore", action="store_true", help="undo --remove")
    p.add_argument("--yes", "-y", action="store_true", help="save without asking to confirm")
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("search", help="do I own this? title, series, author or ISBN")
    p.add_argument("query", nargs="+")
    p.add_argument("--limit", type=int, default=25)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser(
        "enrich", help="fill missing years, pages, publishers and covers from Open Library"
    )
    p.add_argument("--limit", type=int, help="stop after this many books")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("rekey", help="recompute every book's matching keys after the rules change")
    p.set_defaults(func=cmd_rekey)

    p = sub.add_parser("export", help="write the website's data files without publishing")
    p.add_argument("--out", type=Path, default=SITE_DATA, help=f"(default: {SITE_DATA})")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("publish", help="export, test, commit and push the website")
    p.add_argument("--yes", "-y", action="store_true", help="don't ask before committing")
    p.add_argument("--no-tests", action="store_true", help="skip the test run")
    p.add_argument("--no-push", action="store_true", help="commit but don't push")
    p.set_defaults(func=cmd_publish)
