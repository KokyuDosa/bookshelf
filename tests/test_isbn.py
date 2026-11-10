import json
import random
from pathlib import Path

import pytest

from bookshelf.isbn import (
    REASONS,
    InvalidISBN,
    clean,
    is_valid_isbn10,
    is_valid_isbn13,
    looks_like_isbn,
    to_isbn10,
    to_isbn13,
)

CASES = json.loads((Path(__file__).parent / "fixtures" / "normalize_cases.json").read_text("utf-8"))


@pytest.mark.parametrize(("raw", "expected"), CASES["to_isbn13"])
def test_to_isbn13(raw, expected):
    result = to_isbn13(raw)
    assert result == expected
    assert is_valid_isbn13(result)
    assert to_isbn13(result) == result  # idempotent


@pytest.mark.parametrize(("raw", "reason"), CASES["to_isbn13_invalid"])
def test_to_isbn13_rejects_with_reason(raw, reason):
    with pytest.raises(InvalidISBN) as info:
        to_isbn13(raw)
    assert info.value.reason == reason
    assert info.value.raw == raw
    assert isinstance(info.value, ValueError)


def test_helpful_hints():
    with pytest.raises(InvalidISBN, match="leading zero"):
        to_isbn13("306406152")
    with pytest.raises(InvalidISBN, match="scientific notation"):
        to_isbn13("9.78031E+12")


@pytest.mark.parametrize(("isbn13", "expected"), CASES["to_isbn10"])
def test_to_isbn10(isbn13, expected):
    assert to_isbn10(isbn13) == expected


def test_to_isbn10_requires_an_isbn13():
    with pytest.raises(InvalidISBN):
        to_isbn10("0306406152")
    with pytest.raises(InvalidISBN):
        to_isbn10("9780306406158")


@pytest.mark.parametrize(("text", "expected"), CASES["looks_like_isbn"])
def test_looks_like_isbn(text, expected):
    assert looks_like_isbn(text) is expected


def test_validators_never_raise():
    for s in ["", "X", "abc", "0" * 40, "978030640615X"]:
        assert is_valid_isbn10(s) is False
        assert is_valid_isbn13(s) is False


def test_clean_is_idempotent():
    for s in ["ISBN ISBN-13: 978-0", "isbn10 0-8044-2957-x", "  978–—", "ISBNISBN"]:
        assert clean(clean(s)) == clean(s)


def test_round_trips_on_random_isbns():
    rng = random.Random(20261110)
    for _ in range(2000):
        body = "".join(rng.choice("0123456789") for _ in range(9))
        total = sum(w * int(d) for w, d in zip(range(10, 1, -1), body, strict=True))
        c = (11 - total % 11) % 11
        isbn10 = body + ("X" if c == 10 else str(c))
        assert is_valid_isbn10(isbn10)
        isbn13 = to_isbn13(isbn10)
        assert is_valid_isbn13(isbn13) and isbn13.startswith("978")
        assert to_isbn10(isbn13) == isbn10
        assert to_isbn13(to_isbn10(isbn13)) == isbn13


def test_reason_codes_are_the_documented_five():
    assert set(REASONS) == {
        "empty",
        "bad_characters",
        "wrong_length",
        "bad_check_digit",
        "bad_prefix",
    }
