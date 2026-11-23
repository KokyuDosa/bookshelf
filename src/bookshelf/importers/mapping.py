"""Turn one raw export row into a NewBook plus review flags. Pure: no database, no files."""

import re
import tomllib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from bookshelf.catalog import Credit, NewBook
from bookshelf.isbn import InvalidISBN, canonical_barcode, to_isbn13
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


def ordinal(n: int) -> str:
    """2 -> "2nd", 11 -> "11th", 23 -> "23rd"."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# "(Edition 2)", "(2nd Edition)", "(Second Edition)" at the end of a title
EDITION_IN_TITLE = re.compile(
    r"\s*\(\s*(?:edition\s+(?P<n>\d+)|(?P<nth>\d+)(?:st|nd|rd|th)\s+edition|"
    rf"(?P<word>{'|'.join(ORDINALS)})\s+edition)\s*\)\s*$",
    re.IGNORECASE,
)

# "(0786931345)" or "(ISBN 978-0-7869-3134-5)" at the end of a title
ISBN_IN_TITLE = re.compile(
    r"\s*\(\s*(?:isbn[:\s]*)?([\dXx][\dXx\s-]{8,16}[\dXx])\s*\)\s*$", re.IGNORECASE
)

# "… by Douglas R. Hofstadter", "… - by A & B", "… Illustrated By Don Lawrence"
BY_NAMES = re.compile(
    r"[\s,]*(?:[-–—]\s*)?\b(?:(?P<verb>illustrated|translated|edited|written)\s+)?by\s+"
    r"(?P<names>[^()]+?)\s*$",
    re.IGNORECASE,
)
BY_ROLES = {"illustrated": "illustrator", "translated": "translator", "edited": "editor"}
NAME_PARTICLES = {"de", "da", "del", "der", "di", "du", "la", "le", "van", "von", "y", "bin", "al"}

# "Harper & Brothers, 1954" or "MacMillan, New York, 1968": the year and city aren't the name
PUBLISHER_TAIL = re.compile(
    r"^(?P<name>.+?)(?:,\s*(?P<place>[^,\d]+?))?,\s*(?P<year>1[4-9]\d\d|20\d\d)\.?$"
)
YEAR = re.compile(r"(?<!\d)(1[4-9]\d\d|20\d\d)(?!\d)")
MONTH = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?=\s|$|[,;])",
    re.IGNORECASE,
)

# "Prophet Volume 1: Remission", "Capital Volume 1", "Horror on the Orient Express (Vol. 1: London
# to the Alps)", "The History of Sexuality, Volume I: An Introduction"
VOLUME_IN_TITLE = re.compile(
    r"^(?P<series>.*?\w.*?)[\s,:\-–]*\(?\s*\bvol(?:ume)?\.?\s*(?P<num>\d+(?:\.\d+)?|[ivxlc]+)\b"
    r"\s*(?:[:\-–]\s*(?P<rest>[^()]+?))?\s*\)?$",
    re.IGNORECASE,
)
ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}

# "Fray Baroque (ed.)" in an author cell sets the role
CREDIT_ROLE = re.compile(
    r"^(?P<name>.+?)\s*\((?P<role>eds?|editors?|trans|tr|translator|ill|illus|illustrator)\.?\)$",
    re.IGNORECASE,
)
ROLE_WORDS = {
    "ed": "editor",
    "eds": "editor",
    "editor": "editor",
    "editors": "editor",
    "trans": "translator",
    "tr": "translator",
    "translator": "translator",
    "ill": "illustrator",
    "illus": "illustrator",
    "illustrator": "illustrator",
}


def roman_to_int(text: str) -> int | None:
    values = [ROMAN.get(c) for c in text.lower()]
    if not values or None in values:
        return None
    total = sum(
        -v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values)
    )
    return total if total > 0 else None


def parse_credit(text: str) -> Credit:
    """ "Fray Baroque (ed.)" -> an editor; plain names are authors."""
    hit = CREDIT_ROLE.match(text.strip())
    if hit:
        return Credit(hit.group("name").strip(), ROLE_WORDS[hit.group("role").lower()])
    return Credit(text.strip())


def looks_like_names(text: str) -> list[str] | None:
    """ "Peter Hudis & Kevin B Anderson" -> two names. None if any part doesn't look like a
    person's (or organisation's) name: 2-6 words, each capitalised, an initial or a particle."""
    names = [n.strip() for n in re.split(r"\s*(?:&|\band\b)\s*", text) if n.strip()]
    if not names:
        return None
    for name in names:
        words = name.replace(".", ". ").split()
        if not 2 <= len(words) <= 6 or "," in name:
            return None
        for w in words:
            if w.lower() in NAME_PARTICLES or w.lower().rstrip(".") in ("jr", "sr"):
                continue
            if not (w[0].isupper() or (len(w) <= 2 and w[0].isalpha())):
                return None
    return names


def split_publisher(raw: str) -> tuple[str, int | None]:
    """ "MacMillan, New York, 1968" -> ("MacMillan", 1968)."""
    hit = PUBLISHER_TAIL.match(raw)
    if hit and normalize_text(hit.group("name")):
        return hit.group("name").strip(), int(hit.group("year"))
    return raw, None


def split_edition_year(raw: str) -> tuple[str, int | None]:
    """ "1st; 1973" -> ("1st", 1973); "October 1952" -> ("", 1952)."""
    hit = YEAR.search(raw)
    if not hit:
        return raw, None
    rest = MONTH.sub("", raw[: hit.start()] + raw[hit.end() :])
    return " ".join(rest.split()).strip(" ,;/-"), int(hit.group(1))


# Fields most categories don't have. A file without their column is normal, not a warning.
OPTIONAL_FIELDS = frozenset({"line", "series", "volume"})

# "3", "03", "2.5", "Vol. 3", "Volume 3", "v3", "#3", "No. 3"
VOLUME = re.compile(r"(?:vol(?:ume)?\.?|v\.?|#|no\.?)?\s*0*(\d+(?:\.\d+)?)", re.IGNORECASE)


def parse_volume(raw: str) -> float | None:
    """A single volume number, or None for anything else (a range such as "1-3")."""
    hit = VOLUME.fullmatch(raw.strip())
    return float(hit.group(1)) if hit else None


def strip_volume(title: str, volume: float) -> str:
    """ "Happiness, Vol. 3" -> "Happiness" when the volume column also says 3."""
    number = re.escape(f"{volume:g}")
    trimmed = re.sub(
        rf"[\s,:\-\u2013]*(?:vol(?:ume)?\.?|v\.?|#|no\.?)?\s*0*{number}\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )
    return trimmed if normalize_text(trimmed) else title


class RowRejected(Exception):
    """The row can't become a book at all. The message goes into rejects.csv."""


@dataclass
class Mapping:
    source: str
    key_column: str
    multi: str
    fields: dict[str, str]
    line_separator: str | None = None
    extract_copies: bool = False
    extract_format: bool = False
    extract_edition: bool = False  # "(Edition 2)" -> edition 2nd
    extract_isbn: bool = False  # "(0786931345)" -> ISBN, when the barcode is empty
    extract_by_author: bool = False  # "… by Rudy Rucker" -> author, when the column is empty
    extract_volume: bool = False  # "Prophet Volume 1: Remission" -> series, volume, title
    conditions: dict[str, str] = field(default_factory=dict)
    publisher_aliases: dict[str, str] = field(default_factory=dict)

    def columns(self) -> set[str]:
        """The export columns this mapping reads: the key and every mapped field."""
        return {self.key_column, *self.fields.values()}

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
            # "series_separator" is the name used before product lines existed
            line_separator=rules.get("line_separator", rules.get("series_separator")),
            extract_copies=rules.get("extract_copies", False),
            extract_format=rules.get("extract_format", False),
            extract_edition=rules.get("extract_edition", False),
            extract_isbn=rules.get("extract_isbn", False),
            extract_by_author=rules.get("extract_by_author", False),
            extract_volume=rules.get("extract_volume", False),
            conditions={normalize_text(k): v for k, v in cfg.get("condition_values", {}).items()},
            publisher_aliases={
                normalize_text(k): v for k, v in cfg.get("publisher_aliases", {}).items()
            },
        )


@dataclass
class TitleParts:
    title: str
    line: str | None = None
    copies: int = 1
    format: str | None = None
    edition: str | None = None
    isbn: str | None = None
    credits: list[Credit] = field(default_factory=list)  # from "by …" in the title
    by_unsure: str | None = None  # "by …" text that didn't look like names: for review


def tidy(text: str) -> str:
    """Collapse whitespace and drop the space store listings put before colons."""
    return re.sub(r"\s+:", ":", " ".join(text.split()))


def _same_name(a: str, b: str) -> bool:
    return normalize_text(a) == normalize_text(b)


def split_title(
    raw: str, m: Mapping, known_authors: list[str] | tuple[str, ...] = ()
) -> TitleParts:
    """Peel store-listing extras off a title. Each rule only removes text it recognises and
    never empties the title. `known_authors` are the author column's names: "… by X" is cut
    only when X is one of them, or (with an empty column) when X looks like names."""
    parts = TitleParts(tidy(raw))
    sep = m.line_separator
    if sep and sep in parts.title:
        line, rest = (tidy(p) for p in parts.title.split(sep, 1))
        if normalize_text(line) and normalize_text(rest):
            parts.line, parts.title = line, rest
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
        if m.extract_edition and (hit := EDITION_IN_TITLE.search(parts.title)):
            stripped = parts.title[: hit.start()].strip(" ,-")
            if normalize_text(stripped):
                if hit.group("word"):
                    parts.edition = ORDINALS[hit.group("word").lower()]
                else:
                    parts.edition = ordinal(int(hit.group("n") or hit.group("nth")))
                parts.title, changed = stripped, True
        if m.extract_isbn and (hit := ISBN_IN_TITLE.search(parts.title)):
            stripped = parts.title[: hit.start()].strip(" ,-")
            try:
                isbn = to_isbn13(hit.group(1))
            except InvalidISBN:
                isbn = None
            if isbn and normalize_text(stripped):
                parts.isbn, parts.title, changed = isbn, stripped, True
        if m.extract_by_author and (hit := BY_NAMES.search(parts.title)):
            stripped = parts.title[: hit.start()].strip(" ,-–—")
            names = hit.group("names")
            role = BY_ROLES.get((hit.group("verb") or "").lower(), "author")
            plain = role == "author"
            if normalize_text(stripped):
                if plain and any(_same_name(names, a) for a in known_authors):
                    parts.title, changed = stripped, True  # the column already credits them
                elif (found := looks_like_names(names)) and (not plain or not known_authors):
                    parts.credits += [Credit(n, role) for n in found]
                    parts.title, changed = stripped, True
                else:
                    parts.by_unsure = hit.group(0).strip(" ,-–—")
    return parts


def split_volume(title: str) -> tuple[str, float, str] | None:
    """ "Prophet Volume 1: Remission" -> ("Prophet", 1, "Remission"); "Capital Volume 1" ->
    ("Capital", 1, "Capital"). None when the title has no volume in this shape."""
    hit = VOLUME_IN_TITLE.match(title)
    if not hit:
        return None
    num = hit.group("num")
    volume = float(num) if num[0].isdigit() else roman_to_int(num)
    series = hit.group("series").strip(" ,:-–(")
    if not volume or not normalize_text(series):
        return None
    rest = (hit.group("rest") or "").strip()
    return series, float(volume), rest if normalize_text(rest) else series


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
    credits = [parse_credit(name) for name in multi("authors") if normalize_text(name)]
    parts = split_title(cell("title"), m, [c.name for c in credits if c.role == "author"])
    book = NewBook(title=parts.title, line=parts.line, copies=parts.copies, format=parts.format)

    if isbn := cell("isbn"):
        try:
            book.isbn = to_isbn13(isbn)
        except InvalidISBN as exc:
            if code := canonical_barcode(isbn):
                book.barcode = code  # a UPC or store code: kept, so a scan finds the book
            else:
                flags.append(("invalid_isbn", f"barcode {isbn!r} is not an ISBN ({exc.reason})"))
    elif parts.isbn:
        book.isbn = parts.isbn

    book.credits = credits + [
        c for c in parts.credits if not any(_same_name(c.name, k.name) for k in credits)
    ]
    if parts.credits and not any(c.role == "author" for c in credits):
        taken = ", ".join(f"{c.name} ({c.role})" for c in parts.credits)
        flags.append(("check_credits", f"credits taken from the title: {taken}"))
    if parts.by_unsure:
        flags.append(("check_title", f"title may contain names: {parts.by_unsure!r}"))
    book.tags = [t for t in multi("tags") if normalize_text(t)]

    if line := cell("line"):
        book.line = line  # a line column wins over a "Line; Title" title
    if series := cell("series"):
        book.series = series
    if volume := cell("volume"):
        number = parse_volume(volume)
        if number is None:
            flags.append(("bad_value", f"volume {volume!r} is not a single number"))
        else:
            book.series_index = number
            book.title = strip_volume(book.title, number)
            if not book.series:
                book.series = book.title  # manga: "Happiness" vol. 3 is in the series "Happiness"
    elif m.extract_volume and not book.series and (found := split_volume(book.title)):
        book.series, book.series_index, book.title = found

    if edition := cell("edition"):
        edition, year = split_edition_year(edition)
        book.pub_year = year
        if normalize_text(edition):
            book.edition = normalize_edition(edition)
    elif parts.edition:
        book.edition = parts.edition
    if publisher := cell("publisher"):
        if publisher_alias := m.publisher_aliases.get(normalize_text(publisher)):
            publisher, year = publisher_alias, None
        else:
            publisher, year = split_publisher(publisher)
        book.publisher = m.publisher_aliases.get(normalize_text(publisher), publisher)
        book.pub_year = book.pub_year or year
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
