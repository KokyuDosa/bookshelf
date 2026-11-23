"""Importer rules added for the full-collection export (2026-11-19)."""

import pytest

from bookshelf.catalog import Credit, parse_part
from bookshelf.importers.mapping import (
    Mapping,
    looks_like_names,
    map_row,
    ordinal,
    parse_credit,
    roman_to_int,
    split_edition_year,
    split_publisher,
    split_title,
    split_volume,
)
from bookshelf.paths import PROJECT_ROOT

M = Mapping.load(PROJECT_ROOT / "config" / "mappings" / "mystuff2.toml")


def row(**cells):
    return {"item id": "X", **{k.replace("_", " "): v for k, v in cells.items()}}


def credits(book):
    return [(c.name, c.role) for c in book.credits]


# ---------------------------------------------------------------- "by …" in titles


@pytest.mark.parametrize(
    ("title", "author_cell", "expected_title", "expected_credits"),
    [
        (
            "Godel, Escher, Bach : An Eternal Golden Braid by Douglas R. Hofstadter",
            "",
            "Godel, Escher, Bach: An Eternal Golden Braid",
            [("Douglas R. Hofstadter", "author")],
        ),
        # the column already credits them: just cut, no duplicate
        (
            "Interrogating the Real : Selected Writings by Slavoj Zizek",
            "Slavoj Žižek",
            "Interrogating the Real: Selected Writings",
            [("Slavoj Žižek", "author")],
        ),
        # format first, then "- by A & B"
        (
            "The Rosa Luxemburg Reader - by Peter Hudis & Kevin B Anderson (Paperback)",
            "",
            "The Rosa Luxemburg Reader",
            [("Peter Hudis", "author"), ("Kevin B Anderson", "author")],
        ),
        (
            "Tales From Trigan Empire Illustrated By Don Lawrence - Hardcover",
            "",
            "Tales From Trigan Empire",
            [("Don Lawrence", "illustrator")],
        ),
        # an illustrator next to a credited author is added
        (
            "Some Story Illustrated by Ana Ruiz",
            "Ben Ode",
            "Some Story",
            [("Ben Ode", "author"), ("Ana Ruiz", "illustrator")],
        ),
    ],
)
def test_by_names_become_credits(title, author_cell, expected_title, expected_credits):
    b = map_row(row(title=title, author=author_cell), M).book
    assert (b.title, credits(b)) == (expected_title, expected_credits)


@pytest.mark.parametrize(
    "title",
    [
        "Metaphors We Live By",  # nothing after "by"
        "Stand by Me",  # one word: not a name
        "Death by Chocolate",
        "Spell Compendium by Jeff, McArtor, Mike, Sernett, Matthew Grubb",  # garbled
    ],
)
def test_by_text_that_isnt_names_stays(title):
    mapped = map_row(row(title=title), M)
    assert mapped.book.title == title
    assert mapped.book.credits == []


def test_unclear_by_text_is_flagged_and_taken_names_are_too():
    garbled = map_row(row(title="Spell Compendium by Jeff, McArtor, Mike, Sernett"), M)
    assert [r for r, _ in garbled.flags] == ["check_title"]
    taken = map_row(row(title="White Light by Rudy Rucker"), M)
    assert [r for r, _ in taken.flags] == ["check_credits"]
    known = map_row(row(title="White Light by Rudy Rucker", author="Rudy Rucker"), M)
    assert known.flags == []


def test_by_a_different_author_than_the_column_stays_in_the_title():
    b = map_row(row(title="Collected Essays by Ann Other", author="Rudy Rucker"), M).book
    assert b.title == "Collected Essays by Ann Other"


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("Theodore F. Niehaus", ["Theodore F. Niehaus"]),
        ("Peter Hudis & Kevin B Anderson", ["Peter Hudis", "Kevin B Anderson"]),
        ("Ludwig van Beethoven", ["Ludwig van Beethoven"]),
        ("Fei-Ling Davis", ["Fei-Ling Davis"]),
        ("National Audubon Society", ["National Audubon Society"]),
        ("Chocolate", None),
        ("Jeff, McArtor, Mike", None),
        ("the river", None),
    ],
)
def test_looks_like_names(text, names):
    assert looks_like_names(text) == names


# ---------------------------------------------------------------- volumes in titles


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Prophet Volume 1: Remission", ("Prophet", 1.0, "Remission")),
        ("Capital Volume 1", ("Capital", 1.0, "Capital")),
        (
            "The History of Sexuality, Volume 1: An Introduction",
            ("The History of Sexuality", 1.0, "An Introduction"),
        ),
        (
            "Horror on the Orient Express (Vol. 2: Italy to Constantinople)",
            ("Horror on the Orient Express", 2.0, "Italy to Constantinople"),
        ),
        ("Berserk Vol. IV", ("Berserk", 4.0, "Berserk")),
        ("Malleus Monstrorum (Volumes 1 & 2)", None),  # a set, not a volume
        ("Vol. 2: Deities of the Mythos", None),  # no series before it
        ("Partial Differential Equations I: Basic Theory", None),
    ],
)
def test_split_volume(title, expected):
    assert split_volume(title) == expected


def test_volume_rule_only_without_a_volume_value():
    b = map_row(row(title="Prophet Volume 1: Remission"), M).book
    assert (b.series, b.series_index, b.title) == ("Prophet", 1.0, "Remission")
    b = map_row(row(title="Prophet Volume 1: Remission", volume="7"), M).book
    assert b.series_index == 7.0  # the column wins


def test_roman_numerals():
    assert [roman_to_int(r) for r in ("I", "iv", "IX", "XII", "q")] == [1, 4, 9, 12, None]


# ---------------------------------------------------------------- edition, ISBN, years


def test_edition_and_isbn_in_title():
    b = map_row(
        row(title="The Visual Display of Quantitative Information (Edition 2) (Hardcover)"), M
    ).book
    assert (b.title, b.edition, b.format) == (
        "The Visual Display of Quantitative Information",
        "2nd",
        "hardcover",
    )
    b = map_row(row(title="Some Book (Second Edition)", edition="3rd"), M).book
    assert (b.title, b.edition) == ("Some Book", "3rd")  # the cell wins, the title is still cleaned
    b = map_row(row(title="Player's Guide to Faerun (0786931345)"), M).book
    assert (b.title, b.isbn) == ("Player's Guide to Faerun", "9780786931347")
    b = map_row(row(title="Catch-22 (1234567890)"), M).book  # not a valid ISBN: left alone
    assert b.title == "Catch-22 (1234567890)"


def test_ordinal():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101)] == [
        "1st",
        "2nd",
        "3rd",
        "4th",
        "11th",
        "12th",
        "13th",
        "21st",
        "22nd",
        "101st",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MacMillan, New York, 1968", ("MacMillan", 1968)),
        ("Harper & Brothers, 1954", ("Harper & Brothers", 1954)),
        ("Massif Press, 2019", ("Massif Press", 2019)),
        ("Rowan, Rook, and Decard Ltd.", ("Rowan, Rook, and Decard Ltd.", None)),
        ("Dover", ("Dover", None)),
    ],
)
def test_split_publisher(raw, expected):
    assert split_publisher(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1st; 1973", ("1st", 1973)),
        ("October 1952", ("", 1952)),
        ("2nd Printing", ("2nd Printing", None)),
        ("Version 1.0 / First Printing", ("Version 1.0 / First Printing", None)),
    ],
)
def test_split_edition_year(raw, expected):
    assert split_edition_year(raw) == expected


def test_years_land_in_the_book():
    b = map_row(row(title="T", edition="October 1952", publisher="Hutchinson"), M).book
    assert (b.edition, b.pub_year) == (None, 1952)
    b = map_row(
        row(title="T", edition="2nd Printing", publisher="MacMillan, New York, 1968"), M
    ).book
    assert (b.edition, b.publisher, b.pub_year) == ("2nd Printing", "MacMillan", 1968)
    b = map_row(row(title="T", publisher="McGraw-Hill Companies"), M).book
    assert b.publisher == "McGraw-Hill"


# ---------------------------------------------------------------- roles and the "work" part


def test_roles_in_the_author_cell():
    assert parse_credit("Fray Baroque (ed.)") == Credit("Fray Baroque", "editor")
    assert parse_credit("A. V. Miller (trans.)") == Credit("A. V. Miller", "translator")
    assert parse_credit("Don Lawrence (ill.)") == Credit("Don Lawrence", "illustrator")
    assert parse_credit("Plain Name") == Credit("Plain Name")
    b = map_row(
        row(title="Queer Ultraviolence", author="Fray Baroque (ed.)|Tegan Eanelli (ed.)"), M
    ).book
    assert credits(b) == [("Fray Baroque", "editor"), ("Tegan Eanelli", "editor")]


def test_work_part_kind(db):
    assert parse_part("work: Beyond Good and Evil").kind == "work"
    from bookshelf.catalog import NewBook, Part, add_book

    add_book(db, NewBook(title="Omnibus", parts=[Part("Human, All Too Human", "work")]))  # FK holds


def test_rules_off_by_default():
    plain = Mapping("s", "item id", "|", {"title": "title"})
    parts = split_title("Prophet Volume 1 by Ann Other (Edition 2) (0786931345)", plain)
    assert parts.title == "Prophet Volume 1 by Ann Other (Edition 2) (0786931345)"
