"""Import one export file: read -> correct -> map -> match -> write -> report.

Every row runs inside its own SAVEPOINT, so one bad row is rejected without aborting the run,
and the whole file is one transaction, so a crash leaves the database as it was.
"""

import csv
import hashlib
import io
import json
import sqlite3
import tomllib
import zipfile
from collections.abc import Iterator
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bookshelf import migrations
from bookshelf.catalog import add_book, find_by_natural_key, update_book
from bookshelf.importers.mapping import (
    OPTIONAL_FIELDS,
    MappedRow,
    Mapping,
    RowRejected,
    map_row,
)

TEXT_SUFFIXES = {".csv": ",", ".tsv": "\t"}


@dataclass
class RawRow:
    member: str  # file name, or the name inside a zip
    line: int
    cells: dict[str, str]


@dataclass
class Flagged:
    title: str
    reason: str
    details: str


@dataclass
class Report:
    file: str
    dry_run: bool
    rows_read: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    flags: list[Flagged] = field(default_factory=list)
    rejects: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rejects_file: Path | None = None
    backup_file: Path | None = None

    @property
    def flagged(self) -> int:
        return len({f.title for f in self.flags})


# ---------------------------------------------------------------- read


def _read_text(
    name: str, text: str, delimiter: str, m: Mapping, report: Report
) -> Iterator[RawRow]:
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = reader.fieldnames or []
    for required in (m.key_column, m.fields["title"]):
        if required not in header:
            raise ValueError(f"{name}: no {required!r} column; is this a {m.source} export?")
    missing = [c for f, c in m.fields.items() if c not in header and f not in OPTIONAL_FIELDS]
    if missing:
        report.warnings.append(f"{name}: no column(s) {missing}; those fields stay empty")
    absent = [c for f, c in m.fields.items() if c not in header and f in OPTIONAL_FIELDS]
    if absent:
        names = " or ".join(repr(c) for c in absent)
        report.notes.append(f"{name}: no {names} column (fine if this category has none)")
    for row in reader:
        if any((v or "").strip() for v in row.values()):  # skip blank lines
            yield RawRow(name, reader.line_num, {k: v or "" for k, v in row.items() if k})


def read_rows(path: Path, m: Mapping, report: Report) -> Iterator[RawRow]:
    """CSV, TSV, or a zip holding several of them. UTF-8, with or without a byte-order mark."""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        yield from _read_text(
            path.name, path.read_text("utf-8-sig"), TEXT_SUFFIXES[suffix], m, report
        )
    elif suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            for info in sorted(archive.infolist(), key=lambda i: i.filename):
                inner = Path(info.filename)
                if inner.suffix.lower() in TEXT_SUFFIXES and not inner.name.startswith("._"):
                    text = archive.read(info).decode("utf-8-sig")
                    yield from _read_text(
                        info.filename, text, TEXT_SUFFIXES[inner.suffix.lower()], m, report
                    )
    else:
        raise ValueError(f"can't import {path.name}: expected .csv, .tsv or .zip")


def load_corrections(path: Path | None) -> dict[str, dict[str, str]]:
    """{item key: {column: replacement}} from a TOML file; empty when there's no file."""
    if path is None or not path.exists():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- write


def row_hash(mapped: MappedRow) -> str:
    """Hash of the mapped values, so a change in export formatting alone isn't an edit."""
    payload = json.dumps([asdict(mapped.book), mapped.flags], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _flag(conn, run_id, book_id, reason, details, candidate=None) -> bool:
    """Add a review flag unless this book already has one for this reason, open or resolved,
    so a re-import never re-raises something you've already dealt with. True if added."""
    exists = conn.execute(
        "SELECT 1 FROM review_flags WHERE book_id = ? AND reason = ?", (book_id, reason)
    ).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO review_flags (run_id, book_id, candidate_book_id, reason, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, book_id, candidate, reason, details),
        )
    return not exists


def _write_row(
    conn: sqlite3.Connection,
    run_id: int,
    m: Mapping,
    raw: RawRow,
    mapped: MappedRow,
    report: Report,
) -> None:
    digest = row_hash(mapped)
    raw_json = json.dumps(raw.cells, ensure_ascii=False)
    known = conn.execute(
        "SELECT book_id, row_hash FROM source_records WHERE source = ? AND source_key = ?",
        (m.source, mapped.key),
    ).fetchone()

    flags = [(reason, details, None) for reason, details in mapped.flags]
    if known:  # seen before: the source is authoritative for what it supplies
        book_id, old_hash = known
        if old_hash == digest:
            report.unchanged += 1
        else:
            update_book(conn, book_id, mapped.book, "overwrite")
            report.updated += 1
        conn.execute(
            "UPDATE source_records SET row_hash = ?, raw_json = ?, last_seen_run = ? "
            "WHERE source = ? AND source_key = ?",
            (digest, raw_json, run_id, m.source, mapped.key),
        )
    else:
        same_isbn = (
            mapped.book.isbn
            and conn.execute(
                "SELECT book_id FROM books WHERE isbn13 = ?", (mapped.book.isbn,)
            ).fetchone()
        )
        if same_isbn:  # a book already here, e.g. added by hand: only fill its gaps
            book_id = same_isbn[0]
            update_book(conn, book_id, mapped.book, "fill")
            report.updated += 1
        else:
            candidates = find_by_natural_key(conn, mapped.book)
            book_id = add_book(conn, mapped.book)
            report.inserted += 1
            if candidates:
                details = f"same series, title, first author and year as book {candidates[0]}"
                flags.append(("possible_duplicate", details, candidates[0]))
        conn.execute(
            "INSERT INTO source_records (source, source_key, book_id, row_hash, raw_json, "
            "first_seen_run, last_seen_run) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (m.source, mapped.key, book_id, digest, raw_json, run_id, run_id),
        )

    for reason, details, candidate in flags:
        if _flag(conn, run_id, book_id, reason, details, candidate):
            report.flags.append(Flagged(mapped.book.title, reason, details))


def import_file(
    db_path: Path,
    path: Path,
    mapping: Mapping,
    corrections: dict[str, dict[str, str]] | None = None,
    dry_run: bool = False,
) -> Report:
    corrections = corrections or {}
    report = Report(file=path.name, dry_run=dry_run)
    seen: set[str] = set()
    used_corrections: set[str] = set()

    with closing(sqlite3.connect(db_path, autocommit=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if not dry_run:
            report.backup_file = migrations.backup(conn, db_path, version)

        conn.execute("BEGIN")
        try:
            run_id = conn.execute(
                "INSERT INTO import_runs (source, file_name, file_sha256) VALUES (?, ?, ?) "
                "RETURNING run_id",
                (mapping.source, path.name, hashlib.sha256(path.read_bytes()).hexdigest()),
            ).fetchone()[0]

            for raw in read_rows(path, mapping, report):
                report.rows_read += 1
                key = (raw.cells.get(mapping.key_column) or "").strip()
                title = raw.cells.get(mapping.fields["title"], "")
                try:
                    if key in seen:
                        raise RowRejected(f"item {key} appears twice in this file")
                    seen.add(key)
                    cells = dict(raw.cells)
                    if key in corrections:
                        used_corrections.add(key)
                        unknown = set(corrections[key]) - set(cells)
                        if unknown:
                            raise RowRejected(
                                f"correction names unknown column(s) {sorted(unknown)}"
                            )
                        cells.update(corrections[key])
                    mapped = map_row(cells, mapping)
                    conn.execute("SAVEPOINT row")
                    try:
                        _write_row(conn, run_id, mapping, raw, mapped, report)
                        conn.execute("RELEASE row")
                    except Exception:
                        conn.execute("ROLLBACK TO row")
                        conn.execute("RELEASE row")
                        raise
                except (RowRejected, ValueError, sqlite3.IntegrityError) as exc:
                    report.rejected += 1
                    report.rejects.append(
                        {
                            "file": raw.member,
                            "line": str(raw.line),
                            "key": key,
                            "title": title,
                            "reason": str(exc),
                        }
                    )

            for key in sorted(set(corrections) - used_corrections):
                report.warnings.append(f"correction for {key} matched no row in this file")

            status = "dry_run" if dry_run else "committed"
            conn.execute(
                "UPDATE import_runs SET finished_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), "
                "status = ?, rows_read = ?, inserted = ?, updated = ?, unchanged = ?, "
                "flagged = ?, rejected = ? WHERE run_id = ?",
                (
                    status,
                    report.rows_read,
                    report.inserted,
                    report.updated,
                    report.unchanged,
                    report.flagged,
                    report.rejected,
                    run_id,
                ),
            )
            conn.execute("ROLLBACK" if dry_run else "COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    if report.rejects:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report.rejects_file = db_path.parent / "imports" / f"rejects-{path.stem}-{stamp}.csv"
        report.rejects_file.parent.mkdir(parents=True, exist_ok=True)
        with report.rejects_file.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["file", "line", "key", "title", "reason"])
            writer.writeheader()
            writer.writerows(report.rejects)
    return report


def format_report(r: Report) -> str:
    head = "DRY RUN, nothing saved. " if r.dry_run else ""
    lines = [
        f"{head}{r.file}: {r.rows_read} rows read",
        (
            f"  inserted {r.inserted}, updated {r.updated}, unchanged {r.unchanged}, "
            f"rejected {r.rejected}, flagged for review {r.flagged}"
        ),
    ]
    lines += [f"  warning: {w}" for w in r.warnings]
    lines += [f"  note: {n}" for n in r.notes]
    if r.flags:
        lines.append("  New review flags:")
        lines += [f"    {f.title[:48]:48}  {f.reason}: {f.details}" for f in r.flags]
    if r.rejects_file:
        lines.append(f"  Rejected rows written to {r.rejects_file}")
    if r.backup_file:
        lines.append(f"  Backup taken first: {r.backup_file}")
    return "\n".join(lines)
