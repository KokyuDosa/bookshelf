"""The Open Library client, against responses shaped like the documented jscmd=data format.
No test touches the network."""

import json

import pytest

from bookshelf.openlibrary import LookupFailed, OpenLibrary, parse

ISBN = "9780306406157"
RECORD = {
    "url": "https://openlibrary.org/books/OL0000001M/example",
    "key": "/books/OL0000001M",
    "title": "An  Example Book",
    "subtitle": "With a Subtitle",
    "authors": [
        {"url": "https://openlibrary.org/authors/OL1A", "name": "Ada Example"},
        {"url": "https://openlibrary.org/authors/OL2A", "name": "Bo Sample"},
    ],
    "publishers": [{"name": "Example Press"}],
    "publish_date": "c1977",
    "number_of_pages": 148,
    "identifiers": {"isbn_13": [ISBN], "openlibrary": ["OL0000001M"]},
    "cover": {
        "small": "https://covers.openlibrary.org/b/id/1-S.jpg",
        "medium": "https://covers.openlibrary.org/b/id/1-M.jpg",
    },
}


class FakeHTTP:
    """Plays back a list of (status, body) answers and records what was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, user_agent):
        self.calls.append((url, user_agent))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def found_body(isbn=ISBN, record=RECORD):
    return json.dumps({f"ISBN:{isbn}": record})


@pytest.fixture
def client_factory(db):
    sleeps = []

    def make(*answers, contact=""):
        http = FakeHTTP(*answers)
        ol = OpenLibrary(db, fetch=http, contact=contact, sleep=sleeps.append, clock=lambda: 0.0)
        return ol, http, sleeps

    return make


def test_parse_takes_what_bookshelf_stores():
    f = parse(RECORD)
    assert (f.title, f.subtitle, f.authors) == (
        "An Example Book",
        "With a Subtitle",
        ["Ada Example", "Bo Sample"],
    )
    assert (f.publisher, f.pub_year, f.pages) == ("Example Press", 1977, 148)
    assert f.cover_url.endswith("-M.jpg") and f.ol_edition_key == "OL0000001M"


@pytest.mark.parametrize(
    ("date", "year"),
    [("1974", 1974), ("March 1974", 1974), ("c1974", 1974), ("n.d.", None), ("", None)],
)
def test_publish_dates_are_free_text(date, year):
    assert parse({**RECORD, "publish_date": date}).pub_year == year


def test_lookup_and_cache(client_factory):
    ol, http, _ = client_factory((200, found_body()))
    assert ol.lookup(ISBN).title == "An Example Book"
    assert ol.lookup(ISBN).title == "An Example Book"  # second time from api_cache
    assert len(http.calls) == 1 and ol.requests == 1
    assert "bookshelf/" in http.calls[0][1]  # identifies itself in the User-Agent


def test_unknown_isbn_is_none_and_cached(client_factory):
    ol, http, _ = client_factory((200, "{}"))
    assert ol.lookup(ISBN) is None
    assert ol.lookup(ISBN) is None
    assert len(http.calls) == 1


def test_retries_rate_limits_and_server_errors(client_factory):
    ol, http, sleeps = client_factory((429, "slow down"), (503, ""), (200, found_body()))
    assert ol.lookup(ISBN) is not None
    assert len(http.calls) == 3 and 2.0 in sleeps and 4.0 in sleeps  # backs off, doubling


def test_network_failure_raises_lookup_failed(client_factory):
    ol, _http, _ = client_factory(*[OSError("no route to host")] * 4)
    with pytest.raises(LookupFailed, match="no route"):
        ol.lookup(ISBN)


def test_other_http_errors_fail_fast(client_factory):
    ol, http, _ = client_factory((403, "forbidden"))
    with pytest.raises(LookupFailed, match="403"):
        ol.lookup(ISBN)
    assert len(http.calls) == 1


def test_rate_limit_spacing(db):
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    http = FakeHTTP(*[(200, "{}")] * 3)
    ol = OpenLibrary(db, fetch=http, contact="", sleep=sleep, clock=lambda: now[0])
    for isbn in ("9780306406157", "9780804429573", "9791090636071"):
        ol.lookup(isbn)
    assert sleeps == [1.0, 1.0]  # anonymous: one request a second


def test_contact_raises_the_rate(db):
    ol = OpenLibrary(db, fetch=FakeHTTP(), contact="me@example.com")
    assert ol.interval == pytest.approx(1 / 3) and ol.user_agent.endswith("me@example.com")
