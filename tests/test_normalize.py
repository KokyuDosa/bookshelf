import json
import random
import unicodedata
from pathlib import Path

import pytest

from bookshelf.normalize import (
    author_match_key,
    natural_key,
    normalize_text,
    parse_person_name,
    sort_title,
    title_key,
)

CASES = json.loads((Path(__file__).parent / "fixtures" / "normalize_cases.json").read_text("utf-8"))


@pytest.mark.parametrize(("raw", "expected"), CASES["normalize_text"])
def test_normalize_text(raw, expected):
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), CASES["title_key"])
def test_title_key(raw, expected):
    assert title_key(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), CASES["sort_title"])
def test_sort_title(raw, expected):
    assert sort_title(raw) == expected


@pytest.mark.parametrize("fn", [title_key, sort_title])
@pytest.mark.parametrize("raw", ["", "   ", "?!"])
def test_title_functions_reject_textless_titles(fn, raw):
    with pytest.raises(ValueError):
        fn(raw)


@pytest.mark.parametrize(("raw", "display", "sort"), CASES["parse_person_name"])
def test_parse_person_name(raw, display, sort):
    name = parse_person_name(raw)
    assert (name.display_name, name.sort_name) == (display, sort)
    assert parse_person_name(name.sort_name) == name  # sort_name always round-trips


@pytest.mark.parametrize(("raw", "display", "sort"), CASES["parse_person_name"])
def test_display_name_round_trips_unless_compound_surname(raw, display, sort):
    surname = sort.split(",")[0]
    if " " in surname and surname.split()[0].casefold() not in {"le", "van", "de", "von"}:
        pytest.skip("compound surname without a particle: the documented limit")
    assert parse_person_name(display) == parse_person_name(raw)


@pytest.mark.parametrize("raw", CASES["parse_person_name_invalid"])
def test_parse_person_name_rejects(raw):
    with pytest.raises(ValueError):
        parse_person_name(raw)


@pytest.mark.parametrize(("sort", "expected"), CASES["author_match_key"])
def test_author_match_key(sort, expected):
    assert author_match_key(sort) == expected


def test_author_variants_share_one_key():
    variants = ["J.R.R. Tolkien", "J. R. R. Tolkien", "Tolkien, J.R.R.", "Tolkien, J. R. R."]
    keys = {author_match_key(parse_person_name(v).sort_name) for v in variants}
    assert keys == {"tolkien j r r"}


@pytest.mark.parametrize(("title", "author", "year", "expected"), CASES["natural_key"])
def test_natural_key(title, author, year, expected):
    assert natural_key(title, author, year) == expected
    assert natural_key(title, author, year).count("|") == 2


@pytest.mark.parametrize("year", [1399, 2101, True])
def test_natural_key_rejects_bad_years(year):
    with pytest.raises(ValueError):
        natural_key("Dune", "Herbert, Frank", year)


# Property checks: thousands of random strings built from awkward characters.
# (Hypothesis would do this more thoroughly; this needs no extra dependency.)
AWKWARD = "aZ\u00e9 \u00c9 \u00df \ufb01 \u00bd \u216b \u0130 \u03c2 \u03a3 \u01c5 \u2019'\u2018\u02bc&.,;:-\u2013\u2014_/\\|()[]\t\n\u00a0\u200b0123456789 \u03a9 \u0436 \u66f8 \U0001f642 \u0301\u0308"


def random_strings(n=3000, seed=20261110):
    rng = random.Random(seed)
    for _ in range(n):
        yield "".join(rng.choice(AWKWARD) for _ in range(rng.randint(0, 24)))


def test_normalize_text_properties():
    for s in random_strings():
        key = normalize_text(s)
        assert normalize_text(key) == key, repr(s)  # idempotent
        assert key == key.strip() and "  " not in key and "|" not in key
        assert all(unicodedata.category(ch)[0] in "LN" or ch == " " for ch in key), repr(s)
        assert not any(unicodedata.combining(ch) for ch in key)


def test_title_key_never_empty():
    for s in random_strings():
        if normalize_text(s):
            assert title_key(s)
