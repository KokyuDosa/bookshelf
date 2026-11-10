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

## Consequences to remember

- `shelf`, `condition` and `acquired_on` describe all copies of an edition together (row 1).
- Money is stored in integer cents (`purchase_price_cents`) to avoid floating-point rounding.
- Names with a compound surname and no particle ("Gabriel García Márquez") must be entered as "Last, First"; the parser can't tell the surname from a middle name.
- Changing `normalize.py` changes stored keys: run a rekey (planned) after any change to it or after a Python upgrade that alters the shared test cases.
