"""The website's search.js must normalise text exactly like normalize.py, or typed searches miss.

Needs Node.js; skipped when it isn't installed (GitHub's runners have it).
"""

import json
import random
import shutil
import subprocess

import pytest

from bookshelf.isbn import InvalidISBN, to_isbn13
from bookshelf.normalize import normalize_text
from bookshelf.paths import PROJECT_ROOT

NODE = shutil.which("node")
FIXTURES = json.loads(
    (PROJECT_ROOT / "tests" / "fixtures" / "normalize_cases.json").read_text("utf-8")
)
ALPHABET = "aZé É ß ﬁ ½ Ⅻ İ ς Σ ǅ ’'‘ʼ&.,;:-–—_/\\|()[]\t 0123456789 Ω ж 書 が ー ñ ́̈ Mañana"


def random_strings(n=2000, seed=20261117):
    rng = random.Random(seed)
    for _ in range(n):
        yield "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 20)))


def isbn_or_none(text):
    try:
        return to_isbn13(text)
    except InvalidISBN:
        return None


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_search_js_matches_python(tmp_path):
    inputs = [raw for raw, _ in FIXTURES["normalize_text"]] + list(random_strings())
    isbn_inputs = [raw for raw, _ in FIXTURES["to_isbn13"]] + [
        raw for raw, _ in FIXTURES["to_isbn13_invalid"]
    ]
    cases = {
        "normalize": [[s, normalize_text(s)] for s in inputs],
        # ISBN-10/13 strings only: search.js has no use for the label-stripping edge cases
        "isbn": [[s, isbn_or_none(s)] for s in isbn_inputs if s and "E+" not in s],
        "looks_like_isbn": FIXTURES["looks_like_isbn"],
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    run = subprocess.run(
        [NODE, str(PROJECT_ROOT / "tests" / "js" / "search.test.mjs"), str(path)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stderr or run.stdout
