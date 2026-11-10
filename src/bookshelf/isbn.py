"""ISBN cleaning, validation and conversion. Contracts: Schema Workbook, "Helper contracts"."""

import re

DIGITS = frozenset("0123456789")
DASHES = frozenset("-\u2010\u2011\u2012\u2013\u2014\u2015\u2212")  # - ‐ ‑ ‒ – — ― −
LABEL = re.compile(r"^ISBN(?:-?1[03])?:?", re.IGNORECASE)
SCIENTIFIC = re.compile(r"^\d(?:\.\d+)?E\+?\d+$")

REASONS = ("empty", "bad_characters", "wrong_length", "bad_check_digit", "bad_prefix")


class InvalidISBN(ValueError):
    def __init__(self, raw: str, reason: str, hint: str = "") -> None:
        assert reason in REASONS, reason
        self.raw = raw
        self.reason = reason
        super().__init__(f"{reason}: {raw!r}" + (f" ({hint})" if hint else ""))


def clean(raw: str) -> str:
    """Strip an ISBN label, whitespace and dashes; uppercase. Does not validate."""
    s = raw
    while True:  # repeat until stable, so clean(clean(x)) == clean(x)
        nxt = "".join(ch for ch in s if not ch.isspace() and ch not in DASHES).upper()
        nxt = LABEL.sub("", nxt)
        if nxt == s:
            return s
        s = nxt


def _check10(first9: str) -> str:
    total = sum(w * int(d) for w, d in zip(range(10, 1, -1), first9, strict=True))
    c = (11 - total % 11) % 11
    return "X" if c == 10 else str(c)


def _check13(first12: str) -> str:
    total = sum((1 if i % 2 == 0 else 3) * int(d) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def is_valid_isbn10(s: str) -> bool:
    return (
        len(s) == 10
        and set(s[:9]) <= DIGITS
        and (s[9] in DIGITS or s[9] == "X")
        and _check10(s[:9]) == s[9]
    )


def is_valid_isbn13(s: str) -> bool:
    return (
        len(s) == 13 and set(s) <= DIGITS and s[:3] in ("978", "979") and _check13(s[:12]) == s[12]
    )


def to_isbn13(raw: str) -> str:
    """Any written form of an ISBN-10 or ISBN-13 -> the canonical 13-digit string."""
    s = clean(raw)
    if not s:
        raise InvalidISBN(raw, "empty")
    if SCIENTIFIC.match(s):
        raise InvalidISBN(
            raw, "bad_characters", "scientific notation: a spreadsheet turned it into a number"
        )
    if not set(s) <= DIGITS | {"X"} or ("X" in s and not (len(s) == 10 and s.index("X") == 9)):
        raise InvalidISBN(raw, "bad_characters")
    if len(s) == 10:
        if not is_valid_isbn10(s):
            raise InvalidISBN(raw, "bad_check_digit")
        core = "978" + s[:9]
        return core + _check13(core)
    if len(s) == 13:
        if s[:3] not in ("978", "979"):
            raise InvalidISBN(raw, "bad_prefix", "an ISBN-13 starts with 978 or 979")
        if not is_valid_isbn13(s):
            raise InvalidISBN(raw, "bad_check_digit")
        return s
    hint = "leading zero lost in a spreadsheet?" if len(s) == 9 else f"{len(s)} characters"
    raise InvalidISBN(raw, "wrong_length", hint)


def to_isbn10(isbn13: str) -> str | None:
    """ISBN-13 -> ISBN-10, or None for 979 ISBNs, which have no ISBN-10."""
    if len(clean(isbn13)) != 13:
        raise InvalidISBN(isbn13, "wrong_length", "to_isbn10 needs an ISBN-13")
    s = to_isbn13(isbn13)  # raises with the right reason if it isn't valid
    if s.startswith("979"):
        return None
    return s[3:12] + _check10(s[3:12])


def looks_like_isbn(text: str) -> bool:
    """Shape only (no check digit): decides whether a search box query is an ISBN lookup."""
    s = clean(text)
    if len(s) == 13:
        return set(s) <= DIGITS
    if len(s) == 10:
        return set(s[:9]) <= DIGITS and (s[9] in DIGITS or s[9] == "X")
    return False
