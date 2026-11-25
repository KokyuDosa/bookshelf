"""Book details by ISBN from Open Library, politely: cached, rate-limited, retried.

Open Library asks API users to identify themselves in the User-Agent and to stay under
1 request a second (3 a second when the User-Agent includes contact details). Set the
BOOKSHELF_CONTACT environment variable to your email to get the higher rate; it is sent
only to Open Library, in that header.
"""

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

API = "https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
APP = "bookshelf/0.3 (+https://github.com/KokyuDosa/bookshelf)"
RETRY_STATUSES = {429, 500, 502, 503, 504}
YEAR = re.compile(r"(?<!\d)(1[4-9]\d\d|20\d\d)(?!\d)")  # "c1974" has no \b before the 1


class LookupFailed(Exception):
    """Open Library couldn't be reached or kept failing. Manual entry still works."""


@dataclass
class Found:
    title: str
    subtitle: str | None = None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    pub_year: int | None = None
    pages: int | None = None
    cover_url: str | None = None
    ol_edition_key: str | None = None
    subjects: list[str] = field(default_factory=list)  # for genre suggestions; not stored


def _names(items: object) -> list[str]:
    """Subjects come as [{"name": …, "url": …}], occasionally as plain strings."""
    if not isinstance(items, list):
        return []
    names = (i.get("name") if isinstance(i, dict) else i for i in items)
    return [" ".join(n.split()) for n in names if isinstance(n, str) and n.strip()]


def http_get(url: str, user_agent: str, timeout: float = 15) -> tuple[int, str]:
    """(status, body). HTTP errors return their status; network failures raise OSError."""
    request = urllib.request.Request(
        url, headers={"User-Agent": user_agent, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def parse(record: dict) -> Found:
    """One jscmd=data record -> the fields bookshelf stores."""
    year = YEAR.search(record.get("publish_date") or "")  # free text: "1974", "c1974", "March 1974"
    pages = record.get("number_of_pages")
    openlibrary_ids = (record.get("identifiers") or {}).get("openlibrary") or []
    key = (record.get("key") or "").removeprefix("/books/")
    return Found(
        title=" ".join((record.get("title") or "").split()),
        subtitle=" ".join((record.get("subtitle") or "").split()) or None,
        authors=[a["name"] for a in record.get("authors") or [] if a.get("name")],
        publisher=next((p["name"] for p in record.get("publishers") or [] if p.get("name")), None),
        pub_year=int(year.group(1)) if year else None,
        pages=pages if isinstance(pages, int) and pages > 0 else None,
        cover_url=(record.get("cover") or {}).get("medium"),
        ol_edition_key=(openlibrary_ids[0] if openlibrary_ids else key) or None,
        subjects=_names(record.get("subjects")),
    )


class OpenLibrary:
    def __init__(
        self,
        conn: sqlite3.Connection,
        fetch: Callable[[str, str], tuple[int, str]] = http_get,
        contact: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        attempts: int = 4,
    ) -> None:
        contact = contact if contact is not None else os.environ.get("BOOKSHELF_CONTACT", "")
        self.conn = conn
        self.fetch = fetch
        self.user_agent = f"{APP} {contact}".strip()
        self.interval = 1 / 3 if contact else 1.0
        self.sleep = sleep
        self.clock = clock
        self.attempts = attempts
        self.requests = 0  # network requests actually made, for reports and tests
        self._last = -1e9

    def _get(self, url: str) -> str:
        cached = self.conn.execute("SELECT body FROM api_cache WHERE url = ?", (url,)).fetchone()
        if cached:
            return cached[0]
        delay = 2.0
        for attempt in range(1, self.attempts + 1):
            wait = self._last + self.interval - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last = self.clock()
            self.requests += 1
            try:
                status, body = self.fetch(url, self.user_agent)
            except OSError as exc:
                status, body = None, str(exc)
            if status == 200:
                with self.conn:
                    self.conn.execute(
                        "INSERT OR REPLACE INTO api_cache (url, status, body) VALUES (?, ?, ?)",
                        (url, status, body),
                    )
                return body
            if status is not None and status not in RETRY_STATUSES:
                raise LookupFailed(f"Open Library answered HTTP {status}")
            if attempt < self.attempts:
                self.sleep(delay)
                delay *= 2
        reason = f"HTTP {status}" if status else body
        raise LookupFailed(f"Open Library didn't respond after {self.attempts} tries ({reason})")

    def lookup(self, isbn13: str) -> Found | None:
        """Details for one ISBN-13, or None when Open Library doesn't know it."""
        body = self._get(API.format(isbn=isbn13))
        try:
            record = json.loads(body).get(f"ISBN:{isbn13}")
        except (json.JSONDecodeError, AttributeError):
            raise LookupFailed("Open Library sent something that isn't the expected JSON") from None
        if not record:
            return None
        found = parse(record)
        return found if found.title else None
