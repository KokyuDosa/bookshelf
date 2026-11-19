import argparse
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from bookshelf import cli_books, migrations
from bookshelf.db import connect
from bookshelf.importers.mapping import Mapping
from bookshelf.importers.pipeline import format_report, import_file, load_corrections
from bookshelf.paths import DEFAULT_DB, PROJECT_ROOT, SCHEMA_DIR
from bookshelf.seed import seed

SAMPLE_DB = PROJECT_ROOT / "data" / "sample.db"
MAPPINGS_DIR = PROJECT_ROOT / "config" / "mappings"
RESOLUTIONS = ("distinct", "merged", "ignored")


def cmd_import(args: argparse.Namespace) -> int:
    if not args.db.exists():
        print(f"{args.db} does not exist. Run 'bookshelf init' first.", file=sys.stderr)
        return 1
    mapping_file = MAPPINGS_DIR / f"{args.mapping}.toml"
    if not mapping_file.exists():
        print(f"No mapping {mapping_file}", file=sys.stderr)
        return 1
    # Corrections can hold private values (prices), so they live in the git-ignored data folder.
    corrections_file = (
        args.corrections or args.db.parent / "imports" / f"{args.mapping}-corrections.toml"
    )
    try:
        mapping = Mapping.load(mapping_file)
        corrections = load_corrections(corrections_file)
        report = import_file(
            args.db, args.file, mapping, corrections, dry_run=args.dry_run, remap=args.remap
        )
    except (OSError, ValueError) as exc:
        print(f"import failed, nothing saved: {exc}", file=sys.stderr)
        return 1
    if corrections:
        print(f"Applied corrections from {corrections_file}")
    print(format_report(report))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    with closing(connect(args.db)) as conn:
        if args.resolve:
            flag_id, resolution = args.resolve
            if resolution not in RESOLUTIONS or not flag_id.isdigit():
                print(f"Usage: --resolve FLAG_ID {'|'.join(RESOLUTIONS)}", file=sys.stderr)
                return 1
            with conn:
                done = conn.execute(
                    "UPDATE review_flags SET resolution = ?, "
                    "resolved_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                    "WHERE flag_id = ? AND resolved_at IS NULL",
                    (resolution, int(flag_id)),
                ).rowcount
            print(
                f"Resolved flag {flag_id} as {resolution}." if done else f"No open flag {flag_id}."
            )
            return 0 if done else 1
        rows = conn.execute(
            "SELECT f.flag_id, b.title, s.name AS series, f.reason, f.details "
            "FROM review_flags f JOIN books b USING (book_id) LEFT JOIN series s USING (series_id) "
            "WHERE f.resolved_at IS NULL ORDER BY f.reason, b.sort_title"
        ).fetchall()
    if not rows:
        print("Nothing to review.")
    for r in rows:
        title = f"{r['series']}; {r['title']}" if r["series"] else r["title"]
        print(f"{r['flag_id']:5}  {title[:50]:50}  {r['reason']}: {r['details']}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    db_path: Path = args.db
    if db_path.exists():
        print(f"{db_path} already exists. Use 'bookshelf migrate' to upgrade it.", file=sys.stderr)
        return 1
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _, version = migrations.migrate(db_path)
    except migrations.MigrationError as exc:
        db_path.unlink(missing_ok=True)  # leave nothing half-built, so a retry can run
        print(f"init failed: {exc}", file=sys.stderr)
        return 1
    print(f"Created {db_path} at schema version {version}.")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    if not args.db.exists():
        print(f"{args.db} does not exist. Run 'bookshelf init' first.", file=sys.stderr)
        return 1
    try:
        old, new = migrations.migrate(args.db)
    except migrations.MigrationError as exc:
        print(f"migrate failed: {exc}", file=sys.stderr)
        return 1
    print(f"Already at version {new}." if old == new else f"Migrated {old} -> {new}.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """Rebuild the throwaway sample database. Never touches books.db."""
    out: Path = args.out
    if out.resolve() == DEFAULT_DB.resolve():
        print("Refusing to seed your real database; choose another --out.", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    migrations.migrate(out)
    with closing(connect(out)) as conn:
        count = seed(conn)
    print(f"Created {out} with {count} sample books.")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Write schema/snapshot.sql from a freshly migrated database."""
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "snapshot.db"
        migrations.migrate(db)
        with closing(connect(db)) as conn:
            text = migrations.schema_snapshot(conn)
    target = SCHEMA_DIR / "snapshot.sql"
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {target}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bookshelf", description="Book collection tools")
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create a new database at the latest schema").set_defaults(
        func=cmd_init
    )
    sub.add_parser("migrate", help="upgrade an existing database").set_defaults(func=cmd_migrate)
    p_seed = sub.add_parser("seed", help="rebuild a sample database of edge-case books")
    p_seed.add_argument("--out", type=Path, default=SAMPLE_DB, help=f"(default: {SAMPLE_DB})")
    p_seed.set_defaults(func=cmd_seed)
    sub.add_parser("snapshot", help="regenerate schema/snapshot.sql").set_defaults(
        func=cmd_snapshot
    )
    p_import = sub.add_parser("import", help="import an export file (.csv, .tsv or .zip)")
    p_import.add_argument("file", type=Path)
    p_import.add_argument("--mapping", default="mystuff2", help="config/mappings/<name>.toml")
    p_import.add_argument(
        "--corrections",
        type=Path,
        help="per-item fixes (default: data/imports/<mapping>-corrections.toml, if present)",
    )
    p_import.add_argument("--dry-run", action="store_true", help="run every step, save nothing")
    p_import.add_argument(
        "--remap",
        action="store_true",
        help="re-apply the mapping to rows that haven't changed (after editing the mapping file)",
    )
    p_import.set_defaults(func=cmd_import)

    p_review = sub.add_parser("review", help="list open review flags, or resolve one")
    p_review.add_argument(
        "--resolve", nargs=2, metavar=("FLAG_ID", "|".join(RESOLUTIONS)), help="close a flag"
    )
    p_review.set_defaults(func=cmd_review)

    cli_books.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
