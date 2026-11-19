-- 003_product_lines.sql — product lines, separate from series (decided 2026-11-18).
--
-- A product line groups books that belong together without an order ("DND 3.5",
-- "Call of Cthulhu"). A series is ordered and numbered ("Rise of the Runelords" 1-6,
-- "Happiness" vol. 7). A book can have both, so they are two separate columns.
--
-- Until now every "Line; Title" import went into series. This migration moves each series
-- in which no book has a volume number into product_lines; series with numbered volumes stay.

CREATE TABLE product_lines (
    line_id     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_key    TEXT NOT NULL UNIQUE,                 -- normalize.title_key(name), as for series
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
) STRICT;

-- ADD COLUMN with REFERENCES is allowed because the column's default is NULL.
ALTER TABLE books ADD COLUMN line_id INTEGER REFERENCES product_lines (line_id) ON DELETE SET NULL;
CREATE INDEX books_line ON books (line_id);

-- Series without any numbered volume become lines.
CREATE TEMP TABLE moving AS
SELECT s.series_id, s.name, s.name_key, s.created_at
FROM series s
WHERE NOT EXISTS (SELECT 1 FROM books b WHERE b.series_id = s.series_id AND b.series_index IS NOT NULL);

INSERT INTO product_lines (name, name_key, created_at)
SELECT name, name_key, created_at FROM moving;

-- One UPDATE sets line_id and clears series_id: SQLite evaluates every right-hand side
-- against the row as it was, so the subquery still sees the old series_id.
UPDATE books
SET line_id = (SELECT pl.line_id FROM moving m JOIN product_lines pl USING (name_key)
               WHERE m.series_id = books.series_id),
    series_id = NULL
WHERE series_id IN (SELECT series_id FROM moving);

DELETE FROM series WHERE series_id IN (SELECT series_id FROM moving);
DROP TABLE moving;
