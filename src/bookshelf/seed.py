"""Hand-made sample books that exercise the schema's edge cases.

The ISBNs are checksum-valid stand-ins written in different styles, not the real
editions' numbers. Seed a throwaway database, never your real one.
"""

import sqlite3

from bookshelf.catalog import Credit, NewBook, add_book

SEED_BOOKS = [
    # Two copies of one edition (decision 1); ISBN-10 with hyphens; private fields.
    NewBook(
        "The Hobbit",
        [Credit("J.R.R. Tolkien")],
        isbn="0-00-000001-9",
        publisher="Allen & Unwin",
        pub_year=1937,
        format="hardcover",
        language="en",
        copies=2,
        shelf="Living room A2",
        condition="good",
        acquired_on="2019-06-14",
        tags=["fantasy"],
        purchase_price_cents=1899,
        loaned_to="Sam",
        loaned_on="2026-10-01",
    ),
    # Same author spelled differently: must reuse the existing author row (decision 6).
    NewBook(
        "The Fellowship of the Ring",
        [Credit("Tolkien, J. R. R.")],
        isbn="ISBN 0-00-000002-7",
        pub_year=1954,
        format="hardcover",
        language="en",
        series="The Lord of the Rings",
        series_index=1,
        tags=["fantasy"],
    ),
    NewBook(
        "The Two Towers",
        [Credit("J. R. R. Tolkien")],
        isbn="0000000035",
        pub_year=1954,
        format="paperback",
        language="en",
        series="The Lord of the Rings",
        series_index=2,
        tags=["fantasy"],
    ),
    # Co-authors: position 1 and 2.
    NewBook(
        "Good Omens",
        [Credit("Terry Pratchett"), Credit("Neil Gaiman")],
        isbn="0-00-000004-3",
        pub_year=1990,
        format="trade_paperback",
        language="en",
        tags=["fantasy", "humour"],
    ),
    # Surname particle; leading article "A".
    NewBook(
        "A Wizard of Earthsea",
        [Credit("Ursula K. Le Guin")],
        isbn="0000000051",
        pub_year=1968,
        format="mass_market",
        language="en",
        tags=["fantasy"],
    ),
    NewBook(
        "The Left Hand of Darkness",
        [Credit("Le Guin, Ursula K.")],
        isbn="0-00-000006-X",
        pub_year=1969,
        format="mass_market",
        language="en",
        tags=["science fiction"],
    ),
    # Translation with an accented, compound surname given in "Last, First" form.
    NewBook(
        "One Hundred Years of Solitude",
        [Credit("García Márquez, Gabriel"), Credit("Gregory Rabassa", "translator")],
        isbn="0000000078",
        pub_year=1970,
        format="paperback",
        language="en",
    ),
    # Non-Latin title and author.
    NewBook(
        "Мастер и Маргарита",
        [Credit("Михаил Булгаков")],
        isbn="979-1-00-000001-5",
        pub_year=1967,
        format="paperback",
        language="ru",
    ),
    # An anthology: editors only, no 'author' credit.
    NewBook(
        "The Big Book of Science Fiction",
        [Credit("Ann VanderMeer", "editor"), Credit("Jeff VanderMeer", "editor")],
        isbn="978-0-00-000101-6",
        pub_year=2016,
        format="trade_paperback",
        language="en",
        tags=["science fiction", "anthology"],
    ),
    # A novella numbered between books (index 2.5), as an e-book.
    NewBook(
        "Gods of Risk",
        [Credit("James S. A. Corey")],
        pub_year=2012,
        format="ebook",
        language="en",
        series="The Expanse",
        series_index=2.5,
        tags=["science fiction"],
    ),
    # No ISBN, pre-ISBN era, worn copy.
    NewBook(
        "The Time Machine",
        [Credit("H. G. Wells")],
        publisher="Heinemann",
        pub_year=1895,
        format="hardcover",
        language="en",
        condition="fair",
        tags=["science fiction"],
        notes="Spine repaired",
    ),
    # One-word author name and a translator; kept off the public site.
    NewBook(
        "The Republic",
        [Credit("Plato"), Credit("Desmond Lee", "translator")],
        pages=420,
        format="paperback",
        language="en",
        is_public=False,
    ),
    # A soft-deleted book: given away, but remembered so a re-import won't resurrect it.
    NewBook(
        "Dune",
        [Credit("Frank Herbert")],
        isbn="0000000086",
        pub_year=1965,
        format="mass_market",
        language="en",
        tags=["science fiction"],
    ),
]


def seed(conn: sqlite3.Connection) -> int:
    """Load SEED_BOOKS into an empty database. Returns the number of books added."""
    if conn.execute("SELECT count(*) FROM books").fetchone()[0]:
        raise RuntimeError("database already has books; seed only a fresh database")
    with conn:  # one transaction: all of it or none of it
        for book in SEED_BOOKS:
            book_id = add_book(conn, book)
            if book.title == "Dune":
                conn.execute(
                    "UPDATE books SET removed_on = '2026-03-01' WHERE book_id = ?", (book_id,)
                )
    return len(SEED_BOOKS)
