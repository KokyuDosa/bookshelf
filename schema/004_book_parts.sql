-- 004_book_parts.sql — what's inside a set (decided 2026-11-18).
--
-- A slipcase or boxed set is one book: one ISBN, one purchase, one value. Its pieces
-- (two volumes, the slipcase, a folder of handouts) are listed here, in order, with a flag
-- for pieces you no longer have. Pieces have no ISBN of their own: the sets this was built
-- for (Chaosium's Malleus Monstrorum slipcase set) carry only the set's ISBN.

CREATE TABLE part_kinds (
    kind        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,                    -- "volume"
    plural      TEXT NOT NULL,                    -- "volumes"
    sort_order  INTEGER NOT NULL UNIQUE
) STRICT, WITHOUT ROWID;

INSERT INTO part_kinds (kind, label, plural, sort_order) VALUES
    ('volume',   'volume',   'volumes',   10),
    ('booklet',  'booklet',  'booklets',  20),
    ('handouts', 'handouts', 'handouts',  30),
    ('map',      'map',      'maps',      40),
    ('screen',   'screen',   'screens',   50),
    ('cards',    'cards',    'card decks',60),
    ('dice',     'dice',     'dice sets', 70),
    ('slipcase', 'slipcase', 'slipcases', 80),
    ('other',    'other',    'other',     90);

CREATE TABLE book_parts (
    book_id   INTEGER NOT NULL REFERENCES books (book_id) ON DELETE CASCADE,
    position  INTEGER NOT NULL CHECK (position >= 1),  -- 1 = first listed; `edit` numbers by it
    kind      TEXT NOT NULL REFERENCES part_kinds (kind),
    label     TEXT NOT NULL CHECK (length(trim(label)) > 0),  -- "Vol. 1: Monsters of the Mythos"
    have      INTEGER NOT NULL DEFAULT 1 CHECK (have IN (0, 1)),  -- 0 = missing; private
    PRIMARY KEY (book_id, position)
) STRICT, WITHOUT ROWID;
