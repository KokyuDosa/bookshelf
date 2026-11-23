import pytest

from bookshelf.importers.mapping import (
    Mapping,
    RowRejected,
    map_row,
    normalize_edition,
    parse_money_cents,
    split_title,
)
from bookshelf.paths import PROJECT_ROOT

MAPPING = Mapping.load(PROJECT_ROOT / "config" / "mappings" / "mystuff2.toml")


def row(**cells):
    base = {
        "item id": "ID-1",
        "title": "",
        "author": "",
        "publisher": "",
        "genre": "",
        "pages": "",
        "edition": "",
        "quality": "",
        "price": "",
        "item barcode": "",
    }
    base.update({k.replace("_", " "): v for k, v in cells.items()})
    return base


@pytest.mark.parametrize(
    ("raw", "title", "line", "copies", "fmt"),
    [
        ("DND 3.5; Monster Manual", "Monster Manual", "DND 3.5", 1, None),
        ("HEX; Secrets (EGS; 1003)", "Secrets (EGS; 1003)", "HEX", 1, None),  # first ';' only
        ("; Orphan", "; Orphan", None, 1, None),  # no line text: no split
        ("Call of Cthulhu: Arkham", "Call of Cthulhu: Arkham", None, 1, None),  # colon stays
        ("DND 3.5; Player's Handbook (2 Copies)", "Player's Handbook", "DND 3.5", 2, None),
        ("Mysteries, 2 Copies Of This Book", "Mysteries", None, 2, None),
        ("Mouse Guard (Hardcover)", "Mouse Guard", None, 1, "hardcover"),
        ("Numenera Corebook Hardcover", "Numenera Corebook", None, 1, "hardcover"),
        ("Denver - Box Set", "Denver", None, 1, "box_set"),
        (
            "The Yellow King Roleplaying Game Box Set",
            "The Yellow King Roleplaying Game",
            None,
            1,
            "box_set",
        ),
        ("Guide (Hardcover) (3 copies)", "Guide", None, 3, "hardcover"),
        ("Guide (3 copies) (Hardcover)", "Guide", None, 3, "hardcover"),
        ("Hardcover", "Hardcover", None, 1, None),  # would leave no title: kept
        ("Mindjammer : The Game  (Hardcover)", "Mindjammer: The Game", None, 1, "hardcover"),
    ],
)
def test_split_title(raw, title, line, copies, fmt):
    parts = split_title(raw, MAPPING)
    assert (parts.title, parts.line, parts.copies, parts.format) == (title, line, copies, fmt)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Second", "2nd"),
        ("second edition", "2nd"),
        ("7th", "7th"),
        ("2nd Ed.", "2nd"),
        ("Holographic Version", "Holographic Version"),
        ("Version 1.0 / First Printing", "Version 1.0 / First Printing"),
        ("  2nd   Revised ", "2nd Revised"),
    ],
)
def test_normalize_edition(raw, expected):
    assert normalize_edition(raw) == expected


@pytest.mark.parametrize(
    ("raw", "cents"), [("$44.74", 4474), ("$1,234.50", 123450), ("48", 4800), ("$0.99", 99)]
)
def test_parse_money(raw, cents):
    assert parse_money_cents(raw) == cents


@pytest.mark.parametrize("raw", ["abc", "-$1.00", "$-1", "1.234", "NaN", "Infinity", ""])
def test_parse_money_rejects(raw):
    with pytest.raises(ValueError):
        parse_money_cents(raw)


def test_map_full_row():
    mapped = map_row(
        row(
            title="Shadowrun 2E; Lone Star",
            author="Nigel D. Findley|Tom Dowd",
            publisher="Chaosium Inc.",
            genre="TTRPG|Cyberpunk",
            pages="192",
            edition="Second",
            quality="Like New",
            price="$124.12",
            item_barcode="1-55560-230-4",
        ),
        MAPPING,
    )
    b = mapped.book
    assert mapped.key == "ID-1" and mapped.flags == []
    assert (b.line, b.series, b.title, b.edition, b.condition) == (
        "Shadowrun 2E",
        None,
        "Lone Star",
        "2nd",
        "like_new",
    )
    assert [c.name for c in b.credits] == ["Nigel D. Findley", "Tom Dowd"]
    assert b.tags == ["TTRPG", "Cyberpunk"]
    assert (b.publisher, b.pages, b.estimated_value_cents) == ("Chaosium", 192, 12412)
    assert b.isbn == "9781555602307"


def test_bad_optional_values_become_flags_not_rejections():
    mapped = map_row(
        row(
            title="Feng Shui", item_barcode="700040040004", quality="48", pages="many", price="lots"
        ),
        MAPPING,
    )
    assert mapped.book.isbn is None and mapped.book.condition is None
    assert [reason for reason, _ in mapped.flags] == [
        "invalid_isbn",
        "unknown_condition",
        "bad_value",
        "bad_value",
    ]


def test_upc_barcode_is_kept_not_flagged():
    """Feng Shui's real cover code is a UPC: kept as the barcode, so a scan finds the book."""
    mapped = map_row(row(title="Feng Shui", item_barcode="700040040003"), MAPPING)
    assert (mapped.book.isbn, mapped.book.barcode, mapped.flags) == (None, "0700040040003", [])


@pytest.mark.parametrize("cells", [{"item_id": "", "title": "X"}, {"title": "  "}, {"title": "?!"}])
def test_rows_without_key_or_title_are_rejected(cells):
    with pytest.raises(RowRejected):
        map_row(row(**cells), MAPPING)


def test_missing_columns_are_empty():
    mapped = map_row({"item id": "A", "title": "Only a title"}, MAPPING)
    assert mapped.book.title == "Only a title" and mapped.book.credits == []
