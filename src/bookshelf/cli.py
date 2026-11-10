import argparse
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from bookshelf import migrations
from bookshelf.db import connect
from bookshelf.paths import DEFAULT_DB, PROJECT_ROOT, SCHEMA_DIR
from bookshelf.seed import seed

SAMPLE_DB = PROJECT_ROOT / "data" / "sample.db"


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


def not_implemented(args: argparse.Namespace) -> int:
    print(f"'{args.command}' is not implemented yet.")
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
    for name in ("import", "add", "search", "export", "publish"):
        sub.add_parser(name).set_defaults(func=not_implemented)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
