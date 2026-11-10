"""Matching and sorting keys. Contracts: Schema Workbook, "Helper contracts".

Every function here is pure: no I/O, no locale, no global state.
"""

import unicodedata
from dataclasses import dataclass

ARTICLES = frozenset({"the", "a", "an"})

# Removed without leaving a space, so "O'Brien" -> "obrien".
# ' (U+0027), ’ (U+2019), ‘ (U+2018) and ʼ (U+02BC, modifier letter apostrophe).
APOSTROPHES = frozenset({"'", "\u2019", "\u2018", "\u02bc"})

SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv"})

# Words that belong to the surname when they come just before it: "Ursula K. Le Guin".
PARTICLES = frozenset(
    {"le", "la", "de", "du", "da", "di", "del", "della", "des", "van", "von", "der", "den"}
)


def normalize_text(s: str) -> str:
    """Casefolded letters and digits separated by single spaces. Never raises for a str."""
    s = s.replace("&", " and ")
    # casefold first, then decompose: the decomposition can't create new uppercase,
    # and stripping marks last means a second pass finds nothing left to change.
    s = unicodedata.normalize("NFKD", s.casefold())
    out = []
    for ch in s:
        if ch in APOSTROPHES or unicodedata.combining(ch):
            continue
        out.append(ch if unicodedata.category(ch)[0] in "LN" else " ")
    return " ".join("".join(out).split())


def _require_text(value: str, what: str) -> str:
    key = normalize_text(value)
    if not key:
        raise ValueError(f"{what} has no letters or digits: {value!r}")
    return key


def title_key(title: str) -> str:
    """normalize_text(title) minus one leading article. Never empty."""
    key = _require_text(title, "title")
    first, _, rest = key.partition(" ")
    return rest if first in ARTICLES and rest else key


def sort_title(title: str) -> str:
    """ "The Hobbit" -> "Hobbit, The". Casing and accents preserved."""
    _require_text(title, "title")
    tidy = " ".join(title.split())
    first, _, rest = tidy.partition(" ")
    if rest and first.casefold() in ARTICLES:
        return f"{rest}, {first}"
    return tidy


@dataclass(frozen=True)
class PersonName:
    display_name: str  # "Ursula K. Le Guin"
    sort_name: str  # "Le Guin, Ursula K."


def _is_suffix(token: str) -> bool:
    return token.rstrip(".").casefold() in SUFFIXES


def _build(first: str, last: str, suffix: str) -> PersonName:
    if not first:  # one-word name: "Plato"
        return PersonName(
            " ".join(p for p in (last, suffix) if p), ", ".join(p for p in (last, suffix) if p)
        )
    display = " ".join(p for p in (first, last, suffix) if p)
    sort = ", ".join(p for p in (last, first, suffix) if p)
    return PersonName(display, sort)


def parse_person_name(raw: str) -> PersonName:
    """Parse ONE person's name given as "Last, First[, Suffix]" or "First Last [Suffix]".

    Known limit: a compound surname without a particle ("Gabriel García Márquez") can't be
    told apart from a middle name; give such names in "Last, First" form.
    """
    tidy = " ".join(raw.split())
    if not normalize_text(tidy):
        raise ValueError(f"name is blank: {raw!r}")
    parts = [p.strip() for p in tidy.split(",")]
    if len(parts) > 3:
        raise ValueError(f"name has more than two commas: {raw!r}")

    if len(parts) == 3:  # "King, Stephen, Jr."
        last, first, suffix = parts
        return _build(first, last, suffix)

    if len(parts) == 2:
        left, right = parts
        if _is_suffix(right):  # "Stephen King, Jr."
            tokens, suffix = left.split(), right
        else:  # "Le Guin, Ursula K."
            return _build(right, left, "")
    else:  # "Ursula K. Le Guin" or "Stephen King Jr."
        tokens, suffix = tidy.split(), ""
        if len(tokens) > 1 and _is_suffix(tokens[-1]):
            suffix = tokens.pop()

    start = len(tokens) - 1  # the surname begins at the last token...
    while start > 1 and tokens[start - 1].casefold() in PARTICLES:
        start -= 1  # ...or earlier, if particles come before it
    return _build(" ".join(tokens[:start]), " ".join(tokens[start:]), suffix)


def author_match_key(sort_name: str) -> str:
    """The value stored in authors.match_key. Never empty."""
    return _require_text(sort_name, "author name")


def natural_key(title: str, first_author_sort_name: str | None, pub_year: int | None) -> str:
    """ "title|author|year" for spotting the same book without an ISBN. Not unique."""
    if pub_year is not None and (isinstance(pub_year, bool) or not 1400 <= pub_year <= 2100):
        raise ValueError(f"pub_year out of range 1400-2100: {pub_year!r}")
    author = author_match_key(first_author_sort_name) if first_author_sort_name else ""
    year = "" if pub_year is None else str(pub_year)
    return f"{title_key(title)}|{author}|{year}"
