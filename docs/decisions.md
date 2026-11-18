# Design decisions

Source: the Bookshelf Schema Workbook's decision worksheet. Rows 1–6 are my choices; rows 7–15 are defaults taken when the schema was written (2026-11-10) and can still change until the first real import freezes `schema/001_init.sql`.

| # | Decision | Choice | Why |
| --- | --- | --- | --- |
| 1 | What one `books` row represents | An edition, with a `copies` count | I own numerous books where I have two or more copies |
| 2 | Primary key type | `INTEGER PRIMARY KEY` | One database, no plans to merge it with another |
| 3 | Identity of a book with no ISBN | Stored `natural_key` (title + first author + year), never auto-merged; possible matches go to `review_flags` | I own many pre-ISBN books, or books that never had one |
| 4 | ISBN-13 uniqueness | `UNIQUE` | Follows from rows being editions (option b in row 1) |
| 5 | Store ISBN-10 as well? | ISBN-13 only; derive ISBN-10 in code | The derivation is simple |
| 6 | Where author variants get merged | Both: a unique `match_key` at import, plus a merge command (M4) | Easier |
| 7 | Author roles | `role` column on `book_authors` | One join for every kind of credit |
| 8 | Closed value lists | Lookup tables for format and condition; `CHECK` for role | New formats and conditions need only an `INSERT`; roles are a stable set |
| 9 | Series | One series per book: `series_id` + `series_index` on `books` | Simplest; a link table can come later if a book needs two |
| 10 | Date storage | ISO-8601 `TEXT`, UTC timestamps; `pub_year INTEGER` | Readable, sortable, works with SQLite's date functions |
| 11 | Private fields | 1:1 `book_private` table | A leak to the web export becomes structurally harder |
| 12 | Deleting a book | Soft delete: `removed_on`, plus the `active_books` view | A re-import of an old export can't quietly resurrect a book I gave away |
| 13 | Unmapped source columns | Raw row kept as JSON on `source_records` | A field can be mapped later without re-exporting |
| 14 | `updated_at` maintenance | Trigger | Can't be forgotten by application code |
| 15 | Search index sync | Deferred to M4 (migration 002); the table will be `books_fts` | Decide with real search requirements in hand |

## MyStuff2 import (decided 2026-11-17, from the TTRPG export)

| # | Decision | Choice |
| --- | --- | --- |
| I1 | Master copy | SQLite. MyStuff2 is a one-way source: re-import a category until it comes in clean, then stop editing it there. |
| I2 | MyStuff2 "price" | Estimated market value, stored privately as `book_private.estimated_value_cents`. |
| I3 | Edition | New `books.edition` column; spelled-out ordinals become "2nd", anything else is kept as written. |
| I4 | "Line; Title" | Text before the first `;` becomes the series; colons are left alone, because they are often real subtitles. |
| I5 | Conditions | MyStuff2 vocabulary: mint, like_new, excellent, very_good, good, fair, poor (Ex → excellent, VG → very_good). |
| I6 | Copies and format in titles | "(2 Copies)", "(Hardcover)", "Box Set" and similar are stripped from the title into `copies` and `format`; `box_set` added. |
| I7 | Bad barcode | The book is imported without an ISBN and flagged `invalid_isbn` for review; only rows with no ID or no title are rejected. |
| I8 | Other categories | Same mapping for every category; genres arrive as tags, so no automatic category tag. |
| I9 | Data fixes | Per-item corrections in `data/imports/mystuff2-corrections.toml`, applied to raw cells before mapping, so they survive re-imports. Git-ignored because they can hold values. |
| I10 | Publisher spellings | Aliases in the mapping file ("Chaosium Inc." → "Chaosium"). |

Dropped columns (kept in `source_records.raw_json`): item container, bundles, images, attachments, colors, created, updated.

## Website and data entry (decided 2026-11-17)

| # | Decision | Choice |
| --- | --- | --- |
| W1 | Export format | Option A: `site/data/books.json` searched by plain JavaScript; no sql.js. Plus `books.csv` for friends. |
| W2 | Public fields | title, subtitle, series, volume, authors, edition, format, publisher, year, ISBN, copies, tags, cover. Condition and shelf stay private along with everything in `book_private`. |
| W3 | Search rules | Every typed word must start a word of the title, subtitle, series or authors; ISBN-shaped input is an exact lookup. `search.js` and `search.py` follow the same rules, and a test checks JavaScript normalisation against Python on thousands of strings. |
| W4 | Deterministic export | `as_of` is the latest `updated_at`, not the export time, so an unchanged database exports identical files and `publish` has nothing to commit. |
| W5 | Deploy | GitHub Actions runs ruff and pytest (including a privacy check on the published JSON), then deploys `site/`. A failing test keeps the old site live. |
| W6 | Manga and omnibuses | Series name + `series_index` for the volume (`--volume`); "Omnibus" goes in `edition`. No schema change needed. |
| W7 | Open Library | `jscmd=data` endpoint; responses cached in `api_cache` (migration 002); 1 request a second, 3 with `BOOKSHELF_CONTACT`; enrichment fills empty fields only and never subtitles. |
| W8 | Numbered volumes (2026-11-18) | Mappings can fill `series` and `volume`. A volume with no series makes the title the series; a title repeating its volume is trimmed. The volume is part of the natural key (no false duplicate flags between volumes) and of the search key (`happiness 7`). The website and terminal show just "Vol. N" when series and title are the same. `bookshelf rekey` updates existing keys. |

## Consequences to remember

- `shelf`, `condition` and `acquired_on` describe all copies of an edition together (row 1).
- The natural key includes the series name, so "Ashen Stars; Core Rulebook" and "Cyberpunk Red; Core Rulebook" are never flagged as duplicates. It does not include the edition: two editions of one book with no author or year are flagged, and you resolve the flag as `distinct`.
- A re-import overwrites only fields the export supplies; values it leaves empty (such as years filled in by Open Library) are kept. A book first matched by ISBN is only gap-filled, never overwritten.
- A review flag you resolve stays resolved across re-imports.
- Money is stored in integer cents (`purchase_price_cents`) to avoid floating-point rounding.
- Names with a compound surname and no particle ("Gabriel García Márquez") must be entered as "Last, First"; the parser can't tell the surname from a middle name.
- Changing `normalize.py` changes stored keys: run a rekey (planned) after any change to it or after a Python upgrade that alters the shared test cases.
