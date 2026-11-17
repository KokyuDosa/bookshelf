"""`bookshelf publish`: export, test, commit and push, so GitHub Pages updates the site."""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from bookshelf.db import connect
from bookshelf.export import summarize_changes, write_export

DATA_FILES = ("site/data/books.json", "site/data/books.csv")


class PublishError(Exception):
    pass


# Child-process output is decoded explicitly as UTF-8. Without this, Windows decodes it with
# the ANSI code page (cp1252), and books.json read back from git turns into garbage or errors.
TEXT = {"capture_output": True, "encoding": "utf-8", "errors": "replace"}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, check=False, **TEXT)


def publish(
    db_path: Path,
    repo: Path,
    run_tests: bool = True,
    push: bool = True,
    confirm: Callable[[str], bool] = lambda _: True,
    say: Callable[[str], None] = print,
) -> bool:
    """True if something was committed. Raises PublishError with a readable message."""
    if shutil.which("git") is None:
        raise PublishError("git isn't installed or isn't on PATH")
    if _git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
        raise PublishError(f"{repo} isn't a git repository")
    previous = _git(repo, "show", f"HEAD:{DATA_FILES[0]}")
    old_json = previous.stdout.replace("\r\n", "\n") if previous.returncode == 0 else None

    with closing(connect(db_path)) as conn:
        paths = write_export(conn, repo / "site" / "data")
    new_json = paths["books.json"].read_text("utf-8")
    if old_json == new_json:
        say("Nothing to publish: the website already shows this collection.")
        return False
    change = summarize_changes(old_json, new_json)
    summary = (
        f"{change['total']:,} books: {change['added']} added, "
        f"{change['changed']} changed, {change['removed']} removed"
    )
    say(f"Exported {summary}.")

    if run_tests:
        say("Running tests…")
        tests = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=repo,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # the test run writes UTF-8 too
            check=False,
            **TEXT,
        )
        if tests.returncode != 0:
            tail = "\n".join((tests.stdout or tests.stderr).splitlines()[-15:])
            raise PublishError(f"tests failed, nothing published:\n{tail}")

    if not confirm(f"Publish {summary}?"):
        say("Not published. The exported files are in site/data if you want to look.")
        return False

    message = f"Update collection: {change['total']:,} books (+{change['added']} ~{change['changed']} -{change['removed']})"
    for args in (("add", "--", *DATA_FILES), ("commit", "-m", message, "--", *DATA_FILES)):
        step = _git(repo, *args)
        if step.returncode != 0:
            raise PublishError(
                f"git {args[0]} failed: {step.stderr.strip() or step.stdout.strip()}"
            )
    say(f"Committed: {message}")
    if push:
        pushed = _git(repo, "push")
        if pushed.returncode != 0:
            raise PublishError(f"committed, but git push failed: {pushed.stderr.strip()}")
        say("Pushed. GitHub rebuilds the site in a minute or two.")
    return True
