"""Turn one raw export row into a NewBook plus review flags. Pure: no database, no files."""

import re
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bookshelf.catalog import Credit, NewBook
from bookshelf.isbn import InvalidISBN, to_isbn13
from bookshelf.normalize import normalize_text

ORDINALS = {
    "first": "1st",
    "second": "2nd",
    "third": "3rd",
    "fourth": "4th",
    "fifth": "5th",
    "sixth": "6th",
    "seventh": "7th",
    "eighth": "8th",
    "ninth": "9th",
    "tenth": "10th",
}

# Copies written into a title: "(2 Copies)", ", 2 Copies Of This Book"
COPIES = re.compile(
    r"[\s,]*\(?\s*(\d+)\s+cop(?:y|ies)(?:\s+of\s+this\s+book)?\s*\)?\s*$", re.IGNORECASE
)

# Format words at the end of a title: "(Hardcover)", "Hardcover", "- Box Set"
FORMAT = re.compile(
    r"\s*(?:[-–—]\s*)?\(?\s*(hardcover|hardback|paperback|boxed set|box set)\s*\)?\s*$",
    re.IGNORECASE,
)
FORMAT_CODES = {
    "hardcover": "hardcover",
    "hardback": "hardcover",
    "paperback": "paperback",
    "box set": "box_set",
    "boxed set": "box_set",
}


class RowRejected(Exception):
    """The row can't become a book at all. The message goes into rejects.csv."""


@dataclass
class Mapping:
    source: str
    key_column: str
    multi: str
    fields: dict[str, str]
    series_separator: str | None = None
    extract_copies: bool = False
    extract_format: bool = False
    conditions: dict[str, str] = field(default_factory=dict)
    publisher_aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Mapping":
        cfg = tomllib.loads(path.read_text(encoding="utf-8"))
        rules = cfg.get("title_rules", {})
        if "title" not in cfg["fields"]:
            raise ValueError(f"{path.name}: [fields] must map 'title'")
        return cls(
            source=cfg["source"],
            key_column=cfg["key_column"],
            multi=cfg.get("multi_value_delimiter", "|"),
            fields=cfg["fields"],
            series_separator=rules.get("series_separator"),
            extract_copies=rules.get("extract_copies", False),
            extract_format=rules.get("extract_format", False),
            conditions={normalize_text(k): v for k, v in cfg.get("condition_values", {}).items()},
            publisher_aliases={
                normalize_text(k): v for k, v in cfg.get("publisher_aliases", {}).items()
            },
        )


@dataclass
class TitleParts:
    title: str
    series: str | None = None
    copies: int = 1
    format: str | None = None


def tidy(text: str) -> str:
    """Collapse whitespace and drop the space store listings put before colons."""
    return re.sub(r"\s+:", ":", " ".join(text.split()))


def split_title(raw: str, m: Mapping) -> TitleParts:
    parts = TitleParts(tidy(raw))
    sep = m.series_separator
    if sep and sep in parts.title:
        series, rest = (tidy(p) for p in parts.title.split(sep, 1))
        if normalize_text(series) and normalize_text(rest):
            parts.series, parts.title = series, rest
    changed = True
    while changed:  # "(2 Copies) (Hardcover)" in either order
        changed = False
        if m.extract_copies and (hit := COPIES.search(parts.title)):
            stripped = parts.title[: hit.start()].strip(" ,")
            if normalize_text(stripped):
                parts.copies, parts.title, changed = int(hit.group(1)), stripped, True
        if m.extract_format and (hit := FORMAT.search(parts.title)):
            stripped = parts.title[: hit.start()].strip(" ,-")
            if normalize_text(stripped):
                parts.format = FORMAT_CODES[" ".join(hit.group(1).lower().split())]
                parts.title, changed = stripped, True
    return parts


def normalize_edition(raw: str) -> str:
    """ "Second" -> "2nd", "2nd Edition" -> "2nd"; anything else is kept as written."""
    text = re.sub(r"\s+(?:edition|ed\.?)$", "", tidy(raw), flags=re.IGNORECASE)
    words = text.split()
    if words and words[0].lower() in ORDINALS:
        words[0] = ORDINALS[words[0].lower()]
    return " ".join(words)


def parse_money_cents(raw: str) -> int:
    """ "$1,234.50" -> 123450. Raises ValueError for anything that isn't a plain amount."""
    text = raw.strip().removeprefix("$").replace(",", "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"not an amount: {raw!r}") from None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValueError(f"not an amount: {raw!r}")
    return int(amount * 100)


@dataclass
class MappedRow:
    key: str
    book: NewBook
    flags: list[tuple[str, str]]  # (reason, details) for the review list


def map_row(raw: dict[str, str], m: Mapping) -> MappedRow:
    """Raw cells -> a NewBook. Bad optional values become review flags, never rejections."""

    def cell(name: str) -> str:
        column = m.fields.get(name)
        return " ".join((raw.get(column) or "").split()) if column else ""

    def multi(name: str) -> list[str]:
        return [v for v in (" ".join(p.split()) for p in cell(name).split(m.multi)) if v]

    key = (raw.get(m.key_column) or "").strip()
    if not key:
        raise RowRejected(f"no value in key column {m.key_column!r}")
    if not normalize_text(cell("title")):
        raise RowRejected("no title")

    flags: list[tuple[str, str]] = []
    parts = split_title(cell("title"), m)
    book = NewBook(title=parts.title, series=parts.series, copies=parts.copies, format=parts.format)

    if isbn := cell("isbn"):
        try:
            book.isbn = to_isbn13(isbn)
        except InvalidISBN as exc:
            flags.append(("invalid_isbn", f"barcode {isbn!r} is not an ISBN ({exc.reason})"))

    book.credits = [Credit(name) for name in multi("authors") if normalize_text(name)]
    book.tags = [t for t in multi("tags") if normalize_text(t)]

    if publisher := cell("publisher"):
        book.publisher = m.publisher_aliases.get(normalize_text(publisher), publisher)
    if edition := cell("edition"):
        book.edition = normalize_edition(edition)
    if condition := cell("condition"):
        code = m.conditions.get(normalize_text(condition))
        if code:
            book.condition = code
        else:
            flags.append(("unknown_condition", f"condition {condition!r} is not in the mapping"))
    if pages := cell("pages"):
        if pages.isdigit() and int(pages) > 0:
            book.pages = int(pages)
        else:
            flags.append(("bad_value", f"pages {pages!r} is not a positive whole number"))
    if value := cell("estimated_value"):
        try:
            book.estimated_value_cents = parse_money_cents(value)
        except ValueError as exc:
            flags.append(("bad_value", f"estimated value: {exc}"))

    return MappedRow(key=key, book=book, flags=flags)
