"""add, search, enrich, export and publish, driven through the CLI as you'd type them."""

import json
import shutil
import sqlite3
import subprocess
from contextlib import closing

import pytest

from bookshelf import cli_books
from bookshelf.catalog import NewBook, add_book
from bookshelf.cli import main
from bookshelf.db import connect
from bookshelf.openlibrary import OpenLibrary
from bookshelf.publish import publish
from tests.test_openlibrary import ISBN, FakeHTTP, found_body


@pytest.fixture
def ol_answers(monkeypatch):
    """Replace the network: queue answers for Open Library and see the requests made."""
    http = FakeHTTP()
    monkeypatch.setattr(
        cli_books,
        "OpenLibrary",
        lambda conn: OpenLibrary(
            conn, fetch=http, contact="", sleep=lambda s: None, clock=lambda: 0.0
        ),
    )
    return http


def run(db_path, *args):
    return main(["--db", str(db_path), *args])


def book_rows(db_path):
    with closing(connect(db_path)) as conn:
        return conn.execute("SELECT * FROM books ORDER BY book_id").fetchall()


# ---------------------------------------------------------------- add


def test_add_by_isbn_uses_open_library(db_path, ol_answers, capsys):
    ol_answers.answers.append((200, found_body()))
    assert run(db_path, "add", "0-306-40615-2") == 0
    (book,) = book_rows(db_path)
    assert (book["title"], book["isbn13"], book["pub_year"]) == ("An Example Book", ISBN, 1977)
    assert book["cover_url"].endswith("-M.jpg")
    assert "Added as book #1" in capsys.readouterr().out


def test_add_owned_isbn_says_so(db_path, ol_answers, capsys):
    ol_answers.answers.append((200, found_body()))
    run(db_path, "add", ISBN)
    assert run(db_path, "add", ISBN) == 0
    assert "Already in your collection: An Example Book (1 copy)" in capsys.readouterr().out
    assert run(db_path, "add", ISBN, "--another-copy") == 0
    assert book_rows(db_path)[0]["copies"] == 2
    assert len(ol_answers.calls) == 1  # owned books never hit the network


def test_flags_override_open_library(db_path, ol_answers):
    ol_answers.answers.append((200, found_body()))
    run(db_path, "add", ISBN, "--title", "My Title", "--year", "2001", "--format", "Box set")
    (book,) = book_rows(db_path)
    assert (book["title"], book["pub_year"], book["format"]) == ("My Title", 2001, "box_set")


def test_add_manga_volume_by_hand(db_path, capsys):
    assert (
        run(
            db_path,
            "add",
            "--offline",
            "--title",
            "One Piece",
            "--series",
            "One Piece",
            "--volume",
            "12",
            "--edition",
            "Omnibus",
            "--author",
            "Eiichiro Oda",
            "--tag",
            "Manga",
            "--value",
            "$9.99",
        )
        == 0
    )
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT b.series_index, b.edition, s.name, p.estimated_value_cents FROM books b "
            "JOIN series s USING (series_id) JOIN book_private p USING (book_id)"
        ).fetchone()
        tag = conn.execute("SELECT name FROM tags").fetchone()[0]
    assert tuple(row) == (12.0, "Omnibus", "One Piece", 999) and tag == "Manga"
    assert "One Piece, vol. 12" in capsys.readouterr().out


def test_open_library_down_still_adds_with_title(db_path, ol_answers, capsys):
    ol_answers.answers.extend([OSError("offline")] * 4)
    assert run(db_path, "add", ISBN, "--title", "Typed In") == 0
    assert "Enter the details yourself" in capsys.readouterr().out
    assert book_rows(db_path)[0]["title"] == "Typed In"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["add", "--offline"], "No title"),
        (["add", "0-306-40615-3"], "isn't a valid ISBN (bad check digit)"),
        (["add", "--title", "X", "--volume", "3"], "--volume needs --series"),
        (["add", "--title", "X", "--format", "scroll"], "use one of: hardcover"),
        (["add", "--title", "X", "--condition", "battered"], "use one of: mint"),
    ],
)
def test_add_refuses_bad_input(db_path, capsys, args, message):
    assert run(db_path, *args) == 1
    assert message in capsys.readouterr().err
    assert book_rows(db_path) == []


def test_add_possible_duplicate_is_flagged(db_path):
    run(db_path, "add", "--offline", "--title", "Microscope", "--author", "Ben Robbins")
    run(db_path, "add", "--offline", "--title", "Microscope", "--author", "Ben Robbins")
    with closing(connect(db_path)) as conn:
        flag = conn.execute(
            "SELECT book_id, candidate_book_id, reason FROM review_flags"
        ).fetchone()
    assert tuple(flag) == (2, 1, "possible_duplicate")


def test_old_schema_is_refused(tmp_path, capsys):
    db = tmp_path / "old.db"
    sqlite3.connect(db).close()  # version 0
    assert run(db, "search", "x") == 1
    assert "run 'bookshelf migrate'" in capsys.readouterr().err


# ---------------------------------------------------------------- search


@pytest.fixture
def seeded_path(db_path, seeded):
    seeded.commit()
    return db_path


@pytest.mark.parametrize(
    ("query", "code", "expect"),
    [
        (["hob"], 0, "The Hobbit"),
        (["lord", "two"], 0, "The Two Towers"),
        (["Garcia", "Marquez"], 0, "One Hundred Years of Solitude"),
        (["the", "republic"], 0, "The Republic"),  # hidden from the website, not from you
        (["dune"], 1, "Not in the collection"),  # given away (soft-deleted)
        (["978-0-00-000101-6"], 0, "The Big Book of Science Fiction"),
        (["9780306406157"], 1, "No book has ISBN 9780306406157"),
    ],
)
def test_search(seeded_path, capsys, query, code, expect):
    assert run(seeded_path, "search", *query) == code
    assert expect in capsys.readouterr().out


def test_search_bad_isbn(seeded_path, capsys):
    assert run(seeded_path, "search", "0-306-40615-3") == 2


# ---------------------------------------------------------------- enrich and export


def test_enrich_fills_only_empty_fields(db_path, ol_answers, capsys):
    with closing(connect(db_path)) as conn, conn:
        add_book(conn, NewBook("Imported Title", isbn=ISBN, publisher="My Publisher"))
        add_book(conn, NewBook("Not In Open Library", isbn="9780804429573"))
        add_book(conn, NewBook("No ISBN"))
    ol_answers.answers.extend([(200, found_body()), (200, "{}")])
    assert run(db_path, "enrich") == 0
    first = book_rows(db_path)[0]
    assert first["title"] == "Imported Title" and first["publisher"] == "My Publisher"
    assert (first["pub_year"], first["pages"]) == (1977, 148)
    out = capsys.readouterr().out
    assert "1 filled in, 1 unknown to Open Library" in out and "2 network requests" in out
    assert run(db_path, "enrich") == 0
    assert "0 network requests" in capsys.readouterr().out  # all cached


def test_export_command(seeded_path, tmp_path, capsys):
    out = tmp_path / "site-data"
    assert run(seeded_path, "export", "--out", str(out)) == 0
    data = json.loads((out / "books.json").read_text("utf-8"))
    assert data["count"] == 11 and (out / "books.csv").exists()


# ---------------------------------------------------------------- publish


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_publish_commits_and_pushes(seeded_path, tmp_path):
    def git(*args, cwd):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)

    remote, repo = tmp_path / "remote.git", tmp_path / "repo"
    git("init", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    git("init", "-b", "main", str(repo), cwd=tmp_path)
    for key, value in (("user.name", "Test"), ("user.email", "test@example.com")):
        git("config", key, value, cwd=repo)
    (repo / "README.md").write_text("x")
    git("add", ".", cwd=repo)
    git("commit", "-m", "start", cwd=repo)
    git("remote", "add", "origin", str(remote), cwd=repo)
    git("push", "-u", "origin", "main", cwd=repo)

    said = []
    assert publish(seeded_path, repo, run_tests=False, say=said.append) is True
    log = subprocess.run(
        ["git", "log", "--oneline", "origin/main"],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        check=False,
    ).stdout
    assert "Update collection: 11 books (+11 ~0 -0)" in log
    assert publish(seeded_path, repo, run_tests=False, say=said.append) is False  # nothing new
    assert said[-1].startswith("Nothing to publish")

    with closing(connect(seeded_path)) as conn, conn:
        conn.execute("UPDATE books SET title = 'The Hobbit, Annotated' WHERE title = 'The Hobbit'")
    assert (
        publish(
            seeded_path, repo, run_tests=False, push=False, confirm=lambda q: False, say=said.append
        )
        is False
    )
    assert "1 changed" in said[-2]  # asked, declined, nothing committed
