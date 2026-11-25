"""`bookshelf search`: the same matching rules as the website's search.js, run locally."""

from dataclasses import dataclass, field

from bookshelf.isbn import InvalidISBN, canonical_barcode, looks_like_isbn, to_isbn13
from bookshelf.normalize import normalize_text


@dataclass
class Result:
    mode: str  # "empty", "isbn", "barcode", "bad-isbn" or "text"
    books: list[dict] = field(default_factory=list)
    isbn: str | None = None
    barcode: str | None = None


def _score(book: dict, tokens: list[str], phrase: str) -> int:
    words = book["key"].split()
    total = 0
    for t in tokens:
        best = 3 if t in words else 2 if any(w.startswith(t) for w in words) else 0
        if not best:
            return 0
        total += best
    title = normalize_text(book["title"])
    return total + (10 if title == phrase else 5 if title.startswith(phrase) else 0)


def search(books: list[dict], query: str) -> Result:
    """Every word of the query must start a word of the book's title, subtitle, line, series
    or authors. Something shaped like an ISBN is looked up exactly instead."""
    raw = query.strip()
    if not raw:
        return Result("empty")
    code = canonical_barcode(raw)  # also drops a scanned price add-on
    try:
        isbn = to_isbn13(code if code and code[:3] in ("978", "979") else raw)
    except InvalidISBN:
        isbn = None
    if isbn:
        return Result("isbn", [b for b in books if b.get("isbn") == isbn], isbn)
    if code:  # a UPC or store code
        return Result("barcode", [b for b in books if b.get("barcode") == code], barcode=code)
    if looks_like_isbn(raw):
        return Result("bad-isbn")
    phrase = normalize_text(raw)
    tokens = phrase.split()
    if not tokens:
        return Result("empty")
    scored = [(s, b) for b in books if (s := _score(b, tokens, phrase))]
    scored.sort(
        key=lambda sb: (
            -sb[0],
            normalize_text(sb[1].get("line", "")),
            normalize_text(sb[1].get("series", "")),
            sb[1].get("volume", 0),
            sb[1]["key"],
        )
    )
    return Result("text", [b for _, b in scored])


def describe(book: dict) -> str:
    """One line per book for the terminal."""
    title = f"{book['title']}: {book['subtitle']}" if book.get("subtitle") else book["title"]
    parts = [title]
    if book.get("line"):
        parts.append(book["line"])
    if book.get("series"):
        vol = book.get("volume")
        vol = f"{vol:g}" if isinstance(vol, float) else vol  # 12.0 -> 12, 2.5 stays
        same = normalize_text(book["series"]) == normalize_text(book["title"])  # manga: "Happiness"
        if vol is None:
            parts.append(book["series"])
        else:
            parts.append(f"vol. {vol}" if same else f"{book['series']}, vol. {vol}")
    if book.get("authors"):
        parts.append(", ".join(book["authors"]))
    extra = [str(x) for x in (book.get("edition"), book.get("format"), book.get("year")) if x]
    if book.get("copies", 1) > 1:
        extra.append(f"{book['copies']} copies")
    if extra:
        parts.append(" · ".join(extra))
    if book.get("contents"):
        parts.append("contains " + " + ".join(book["contents"]))
    return "  —  ".join(parts)


# ---------------------------------------------------------------- genres (tags)


def _tag_key(name: str) -> str:
    """Case, accents and a plural ending don't matter: "graphic novels" = "Graphic Novel"."""
    key = normalize_text(name)
    if key.endswith("ies") and len(key) > 4:
        return key[:-3] + "y"
    if key.endswith("s") and not key.endswith("ss") and len(key) > 3:
        return key[:-1]
    return key


def genre_counts(books: list[dict]) -> list[tuple[str, int]]:
    """Every genre on these books with its number of books, most used first."""
    counts: dict[str, int] = {}
    for b in books:
        for t in b.get("tags", []):
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda tc: (-tc[1], tc[0].casefold()))


def resolve_genres(books: list[dict], wanted: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Typed genre names -> the genres as you spelled them in the collection.

    Returns (found, unknown) where unknown maps each name that matched nothing to the genres
    that look close (containing it, or starting the same way), for a "did you mean" hint.
    """
    by_key = {_tag_key(name): name for name, _ in genre_counts(books)}
    found: list[str] = []
    unknown: dict[str, list[str]] = {}
    for name in wanted:
        hit = by_key.get(_tag_key(name))
        if hit:
            if hit not in found:
                found.append(hit)
            continue
        typed = normalize_text(name)
        unknown[name] = [
            g for k, g in by_key.items() if typed and (typed in k or k.startswith(typed[:3]))
        ][:5]
    return found, unknown


def with_genres(books: list[dict], genres: list[str]) -> list[dict]:
    """Books that have every one of `genres`."""
    want = {_tag_key(g) for g in genres}
    return [b for b in books if want <= {_tag_key(t) for t in b.get("tags", [])}]


def browse_order(books: list[dict]) -> list[dict]:
    """Line, then series and volume, then title: the website's A-to-Z order."""
    return sorted(
        books,
        key=lambda b: (
            normalize_text(b.get("line", "")),
            normalize_text(b.get("series", "")) or b["key"],
            b.get("volume", 0),
            b["key"],
        ),
    )
