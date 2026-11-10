-- 001_init.sql — initial schema for the bookshelf database
--
-- Runner contract (see the Schema Workbook, "How migrations work"):
--   * the runner wraps this file in BEGIN ... COMMIT and sets PRAGMA user_version = 1
--   * foreign keys are switched on per connection by application code, not here
--   * once this file has run against your real database, never edit it — write 002_*.sql instead
--
-- Decisions (worksheet row numbers):
--   1  one row per edition, with a copies count           (yours)
--   2  INTEGER PRIMARY KEY everywhere                     (yours)
--   3  natural key stored and indexed, never auto-merged;
--      possible matches go to review_flags                (yours)
--   4  isbn13 UNIQUE                                      (yours)
--   5  ISBN-13 only; ISBN-10 derived in code              (yours)
--   6  authors.match_key UNIQUE + a merge command (M4)    (yours)
--   7  role column on book_authors                        (default picked for you)
--   8  lookup tables for format and condition; CHECK for role
--   9  one series per book: series_id + series_index on books
--   10 ISO-8601 TEXT dates and UTC timestamps; pub_year INTEGER
--   11 private fields in a 1:1 book_private table
--   12 soft delete: books.removed_on, plus an active_books view
--   13 raw source row kept as JSON on source_records
--   14 updated_at maintained by trigger
--   15 books_fts deferred to a later migration (M4)


-- ---------------------------------------------------------------------------
-- Lookup tables (row 8). Their rows are part of the schema, so they live here.
-- Edit the lists freely until this file is frozen; after that, add rows in a
-- new migration with a plain INSERT.
-- ---------------------------------------------------------------------------

CREATE TABLE formats (
    format      TEXT PRIMARY KEY,                 -- stable code stored on books
    label       TEXT NOT NULL,                    -- what the UI shows
    sort_order  INTEGER NOT NULL UNIQUE
) STRICT, WITHOUT ROWID;

INSERT INTO formats (format, label, sort_order) VALUES
    ('hardcover',        'Hardcover',             10),
    ('trade_paperback',  'Trade paperback',       20),
    ('mass_market',      'Mass-market paperback', 30),
    ('paperback',        'Paperback (other)',     40),
    ('ebook',            'E-book',                50),
    ('audiobook',        'Audiobook',             60),
    ('other',            'Other',                 90);

CREATE TABLE conditions (
    condition   TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    sort_order  INTEGER NOT NULL UNIQUE
) STRICT, WITHOUT ROWID;

INSERT INTO conditions (condition, label, sort_order) VALUES
    ('new',        'New',        10),
    ('fine',       'Fine',       20),
    ('very_good',  'Very good',  30),
    ('good',       'Good',       40),
    ('fair',       'Fair',       50),
    ('poor',       'Poor',       60);


-- ---------------------------------------------------------------------------
-- Catalogue
-- ---------------------------------------------------------------------------

CREATE TABLE series (
    series_id   INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_key    TEXT NOT NULL UNIQUE,             -- normalised in Python
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
) STRICT;

CREATE TABLE books (
    book_id         INTEGER PRIMARY KEY,

    -- titles
    title           TEXT NOT NULL CHECK (length(trim(title)) > 0),
    subtitle        TEXT CHECK (subtitle IS NULL OR length(trim(subtitle)) > 0),  -- NULL, never ''
    sort_title      TEXT NOT NULL,                -- "Hobbit, The"; computed in Python
    title_key       TEXT NOT NULL,                -- normalised title; computed in Python
    natural_key     TEXT NOT NULL,                -- title_key + first author + year (row 3); not unique

    -- edition identity (rows 1, 4, 5)
    isbn13          TEXT UNIQUE CHECK (
                        isbn13 IS NULL OR (
                            length(isbn13) = 13
                            AND isbn13 NOT GLOB '*[^0-9]*'
                            AND substr(isbn13, 1, 3) IN ('978', '979')
                        )
                    ),                            -- check digit validated in Python
    publisher       TEXT,
    pub_year        INTEGER CHECK (pub_year IS NULL OR pub_year BETWEEN 1400 AND 2100),
    pages           INTEGER CHECK (pages IS NULL OR pages > 0),
    format          TEXT REFERENCES formats (format),
    language        TEXT CHECK (language IS NULL
                                OR (length(language) BETWEEN 2 AND 3 AND language = lower(language))),

    -- series (row 9)
    series_id       INTEGER REFERENCES series (series_id) ON DELETE SET NULL,
    series_index    REAL CHECK (series_index IS NULL OR series_index >= 0),

    -- the copies you hold (row 1); shelf and condition describe them as a group
    copies          INTEGER NOT NULL DEFAULT 1 CHECK (copies >= 1),
    shelf           TEXT,
    condition       TEXT REFERENCES conditions (condition),
    acquired_on     TEXT CHECK (acquired_on IS NULL OR date(acquired_on) IS acquired_on),

    -- enrichment
    ol_edition_key  TEXT UNIQUE,                  -- Open Library edition id, e.g. OL7353617M
    cover_url       TEXT,

    -- publishing and lifecycle (rows 11, 12)
    is_public       INTEGER NOT NULL DEFAULT 1 CHECK (is_public IN (0, 1)),
    removed_on      TEXT CHECK (removed_on IS NULL OR date(removed_on) IS removed_on),

    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    CHECK (series_index IS NULL OR series_id IS NOT NULL)
) STRICT;

CREATE INDEX books_title_key   ON books (title_key);
CREATE INDEX books_natural_key ON books (natural_key);
CREATE INDEX books_series      ON books (series_id, series_index);
CREATE INDEX books_active      ON books (removed_on) WHERE removed_on IS NULL;

-- Row 14: stamp updated_at on every change unless the statement set it itself.
-- The WHEN clause also stops the trigger re-firing on its own UPDATE.
CREATE TRIGGER books_touch_updated_at
AFTER UPDATE ON books
FOR EACH ROW
WHEN NEW.updated_at IS OLD.updated_at
BEGIN
    UPDATE books
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
     WHERE book_id = NEW.book_id;
END;

CREATE TABLE authors (
    author_id      INTEGER PRIMARY KEY,
    display_name   TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    sort_name      TEXT NOT NULL,                 -- "Le Guin, Ursula K."
    match_key      TEXT NOT NULL UNIQUE,          -- normalised from sort_name (row 6)
    ol_author_key  TEXT UNIQUE,                   -- e.g. OL33421A
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
) STRICT;

CREATE TABLE book_authors (
    book_id    INTEGER NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    author_id  INTEGER NOT NULL REFERENCES authors (author_id) ON DELETE RESTRICT,
    role       TEXT NOT NULL DEFAULT 'author'
               CHECK (role IN ('author', 'editor', 'translator', 'illustrator', 'contributor')),
    position   INTEGER NOT NULL CHECK (position >= 1),   -- 1 = first credited
    PRIMARY KEY (book_id, author_id, role)
) STRICT, WITHOUT ROWID;

CREATE INDEX book_authors_author ON book_authors (author_id);

CREATE TABLE tags (
    tag_id      INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_key    TEXT NOT NULL UNIQUE
) STRICT;

CREATE TABLE book_tags (
    book_id  INTEGER NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags (tag_id) ON DELETE CASCADE,
    PRIMARY KEY (book_id, tag_id)
) STRICT, WITHOUT ROWID;

CREATE INDEX book_tags_tag ON book_tags (tag_id);


-- ---------------------------------------------------------------------------
-- Private (row 11). Never selected by the web export.
-- ---------------------------------------------------------------------------

CREATE TABLE book_private (
    book_id               INTEGER PRIMARY KEY REFERENCES books (book_id) ON DELETE CASCADE,
    purchase_price_cents  INTEGER CHECK (purchase_price_cents IS NULL OR purchase_price_cents >= 0),
    notes                 TEXT,
    loaned_to             TEXT,
    loaned_on             TEXT CHECK (loaned_on IS NULL OR date(loaned_on) IS loaned_on),
    CHECK (loaned_on IS NULL OR loaned_to IS NOT NULL)
) STRICT;


-- ---------------------------------------------------------------------------
-- Bookkeeping: idempotent imports (M2) and the review queue (row 3)
-- ---------------------------------------------------------------------------

CREATE TABLE import_runs (
    run_id       INTEGER PRIMARY KEY,
    source       TEXT NOT NULL,                   -- mapping name, e.g. 'mystuff2'
    file_name    TEXT NOT NULL,
    file_sha256  TEXT NOT NULL CHECK (length(file_sha256) = 64),
    started_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'committed', 'rolled_back', 'dry_run')),
    rows_read    INTEGER NOT NULL DEFAULT 0 CHECK (rows_read >= 0),
    inserted     INTEGER NOT NULL DEFAULT 0 CHECK (inserted >= 0),
    updated      INTEGER NOT NULL DEFAULT 0 CHECK (updated >= 0),
    unchanged    INTEGER NOT NULL DEFAULT 0 CHECK (unchanged >= 0),
    flagged      INTEGER NOT NULL DEFAULT 0 CHECK (flagged >= 0),
    rejected     INTEGER NOT NULL DEFAULT 0 CHECK (rejected >= 0)
) STRICT;

CREATE TABLE source_records (
    source          TEXT NOT NULL,
    source_key      TEXT NOT NULL,                -- MyStuff2 item id, or a hash of key fields
    book_id         INTEGER NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    row_hash        TEXT NOT NULL,                -- hash of mapped + normalised values
    raw_json        TEXT NOT NULL CHECK (json_valid(raw_json)),   -- row 13
    first_seen_run  INTEGER NOT NULL REFERENCES import_runs (run_id),
    last_seen_run   INTEGER NOT NULL REFERENCES import_runs (run_id),
    PRIMARY KEY (source, source_key)
) STRICT;

CREATE INDEX source_records_book      ON source_records (book_id);
CREATE INDEX source_records_last_seen ON source_records (last_seen_run);

CREATE TABLE review_flags (
    flag_id            INTEGER PRIMARY KEY,
    run_id             INTEGER REFERENCES import_runs (run_id),     -- NULL when raised by hand entry
    book_id            INTEGER NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    candidate_book_id  INTEGER REFERENCES books (book_id) ON DELETE CASCADE,
    reason             TEXT NOT NULL CHECK (length(trim(reason)) > 0),  -- e.g. 'natural_key_match'
    details            TEXT,
    created_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    resolved_at        TEXT,
    resolution         TEXT CHECK (resolution IS NULL OR resolution IN ('merged', 'distinct', 'ignored')),
    CHECK ((resolved_at IS NULL) = (resolution IS NULL)),
    CHECK (candidate_book_id IS NULL OR candidate_book_id <> book_id)
) STRICT;

CREATE INDEX review_flags_open      ON review_flags (created_at) WHERE resolved_at IS NULL;
CREATE INDEX review_flags_book      ON review_flags (book_id);
CREATE INDEX review_flags_candidate ON review_flags (candidate_book_id);
CREATE INDEX review_flags_run       ON review_flags (run_id);


-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- Row 12: everything that isn't soft-deleted. Query this, not books, by default.
CREATE VIEW active_books AS
SELECT * FROM books WHERE removed_on IS NULL;