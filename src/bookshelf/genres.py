"""Genre suggestions: Open Library subjects -> genres (tags) you already use. Never new ones."""

import sqlite3
import tomllib
from pathlib import Path

from bookshelf.normalize import normalize_text
from bookshelf.paths import PROJECT_ROOT

ALIASES_FILE = PROJECT_ROOT / "config" / "genre_aliases.toml"


def _forms(text: str) -> list[str]:
    """The ways a subject can name a genre: whole, before "--", before a comma; each also
    without a plural ending ("graphic novels" -> "graphic novel", "biographies" -> "biography")."""
    whole = normalize_text(text)
    parts = [whole, normalize_text(text.split("--")[0]), normalize_text(text.split(",")[0])]
    forms: list[str] = []
    for p in parts:
        for f in (p, _singular(p)):
            if f and f not in forms:
                forms.append(f)
    return forms


def _singular(key: str) -> str:
    if key.endswith("ies") and len(key) > 4:
        return key[:-3] + "y"
    if key.endswith("s") and not key.endswith("ss") and len(key) > 3:
        return key[:-1]
    return key


class GenreMatcher:
    def __init__(self, allowed: list[str], aliases: dict[str, str] | None = None):
        """allowed: genre names; the only names suggest() will ever return."""
        self.by_key: dict[str, str] = {}
        for name in allowed:
            for key in {normalize_text(name), _singular(normalize_text(name))}:
                self.by_key.setdefault(key, name)
        self.aliases: dict[str, str] = {}
        for subject, genre in (aliases or {}).items():
            target = self.by_key.get(normalize_text(genre)) or self.by_key.get(
                _singular(normalize_text(genre))
            )
            if target:  # an alias to a genre you don't use is ignored
                for key in {normalize_text(subject), _singular(normalize_text(subject))}:
                    self.aliases[key] = target

    def suggest(self, subjects: list[str]) -> list[str]:
        found: list[str] = []
        for subject in subjects:
            for form in _forms(subject):
                genre = self.aliases.get(form) or self.by_key.get(form)
                if genre:
                    if genre not in found:
                        found.append(genre)
                    break
        return found


def load_aliases(path: Path = ALIASES_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    return dict(tomllib.loads(path.read_text(encoding="utf-8")).get("aliases", {}))


def matcher_for(
    conn: sqlite3.Connection, extra: list[str] = (), path: Path = ALIASES_FILE
) -> GenreMatcher:
    """Genres in use (a tag on at least one book), plus `extra` (a session's --tag values)."""
    used = [
        name
        for (name,) in conn.execute(
            "SELECT t.name FROM tags t WHERE EXISTS "
            "(SELECT 1 FROM book_tags bt WHERE bt.tag_id = t.tag_id) ORDER BY t.name"
        )
    ]
    return GenreMatcher([*extra, *used], load_aliases(path))
