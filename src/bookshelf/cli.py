import argparse
import sys
from pathlib import Path

from bookshelf import migrations
from bookshelf.paths import DEFAULT_DB


def handle_init(args: argparse.Namespace) -> int:
    db_path: Path = args.db
    if db_path.exists():
        print(f"{db_path} already exists. Use 'bookshelf migrate' to upgrade it.", file=sys.stderr)
        return 1
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        _, version = migrations.migrate(db_path)   
    except migrations.MigrationError as e:
        db_path.unlink(missing_ok=True) # leave nothing half-built, so a retry can run
        print(f"init failed: {e}", file=sys.stderr)
        return 1

    print(f"Created {db_path} at schema version {version}")
    return 0
    


def handle_migrate(args: argparse.Namespace) -> int:
    if not args.db.exists():
        print(f"{args.db} does not exist. Run 'bookshelf init' first", file=sys.stderr)
        return 1

    try:
        old, new = migrations.migrate(args.db)
    except migrations.MigrationError as e:
        print(f"migrate failed: {e}", file=sys.stderr)
        return 1

    print(f"Already at version {new}." if old == new else f"Migrated {old} -> {new}")
    return 0


def not_implemented(args: argparse.Namespace) -> int:
    print(f"'{args.command}' is not implemented yet.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bookshelf", description="Book collection tools")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"database file (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create a new database at the latest schema").set_defaults(func=handle_init)
    sub.add_parser("migrate", help="upgrade an existing database").set_defaults(func=handle_migrate)

    for name in ("import", "add", "search", "export", "publish"):
        sub.add_parser(name).set_defaults(func=not_implemented)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
