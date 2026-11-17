"""What leaves the database for the public website, and only that."""

import json

from bookshelf.export import (
    PUBLIC_FIELDS,
    books_csv,
    books_json,
    public_books,
    summarize_changes,
    write_export,
)
from bookshelf.paths import PROJECT_ROOT

PRIVATE_COLUMNS = {
    "purchase_price_cents",
    "estimated_value_cents",
    "notes",
    "loaned_to",
    "loaned_on",
}
SEED_PRIVATE_VALUES = ["1899", "Sam", "Spine repaired", "2026-10-01", "Living room A2"]


def test_only_public_fields(seeded):
    for book in public_books(seeded):
        assert set(book) <= set(PUBLIC_FIELDS)


def test_no_private_values_leak(seeded):
    text = books_json(seeded) + books_csv(seeded)
    for value in SEED_PRIVATE_VALUES:  # price, borrower, note, loan date, shelf
        assert value not in text
    for column in PRIVATE_COLUMNS | {"shelf", "condition"}:
        assert column not in text


def test_hidden_and_removed_books_are_left_out(seeded):
    titles = {b["title"] for b in public_books(seeded)}
    assert "The Republic" not in titles  # is_public = 0
    assert "Dune" not in titles  # soft-deleted
    assert len(titles) == 11


def test_export_is_deterministic(seeded):
    assert books_json(seeded) == books_json(seeded)
    data = json.loads(books_json(seeded))
    assert data["count"] == len(data["books"]) and data["as_of"]


def test_book_shape(seeded):
    by_title = {b["title"]: b for b in public_books(seeded)}
    hobbit = by_title["The Hobbit"]
    assert hobbit["authors"] == ["J.R.R. Tolkien"] and hobbit["copies"] == 2
    assert hobbit["key"] == "the hobbit j r r tolkien"
    assert by_title["Gods of Risk"]["volume"] == 2.5
    assert by_title["The Two Towers"]["volume"] == 2  # whole numbers print without .0
    assert "subtitle" not in hobbit  # empty fields are left out


def test_csv_opens_in_excel(seeded, tmp_path):
    paths = write_export(seeded, tmp_path)
    raw = paths["books.csv"].read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # byte-order mark: Excel then reads UTF-8
    assert "García Márquez" in raw.decode("utf-8-sig")


def test_change_summary():
    old = json.dumps({"books": [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}]})
    new = json.dumps({"books": [{"id": 1, "title": "A2"}, {"id": 3, "title": "C"}]})
    assert summarize_changes(old, new) == {"added": 1, "removed": 1, "changed": 1, "total": 2}
    assert summarize_changes(None, new)["added"] == 2


def test_committed_site_data_is_public_only():
    """Runs in CI against the books.json you actually publish."""
    path = PROJECT_ROOT / "site" / "data" / "books.json"
    if not path.exists():
        return
    data = json.loads(path.read_text("utf-8"))
    for book in data["books"]:
        assert set(book) <= set(PUBLIC_FIELDS), set(book) - set(PUBLIC_FIELDS)


def test_gitignore_keeps_private_data_out_and_site_data_in():
    """Runs wherever the project is a git checkout (your PC, GitHub's runners)."""
    import shutil
    import subprocess

    if shutil.which("git") is None:
        return

    def ignored(path):
        return subprocess.run(
            ["git", "check-ignore", "-q", path], cwd=PROJECT_ROOT, capture_output=True, check=False
        ).returncode

    if ignored("README.md") == 128:  # not a git repository
        return
    assert ignored("data/books.db") == 0
    assert ignored("data/imports/mystuff2-corrections.toml") == 0
    assert ignored("site/data/books.json") == 1
    assert ignored("site/data/books.csv") == 1
