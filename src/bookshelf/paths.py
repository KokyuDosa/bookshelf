from pathlib import Path

# src/bookshelf/paths.py -> parents[2] is the repo root (works with the editable install)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = PROJECT_ROOT / "schema"
DEFAULT_DB = PROJECT_ROOT / "data" / "books.db"
