-- 005_work_parts.sql — a "work" part kind (decided 2026-11-19).
--
-- For one volume holding several works: "Human, All Too Human" and "Beyond Good and Evil" in a
-- single Wordsworth edition, or a manga omnibus collecting volumes 1-3. Listing each work as a
-- part makes every title searchable without splitting the book.

INSERT INTO part_kinds (kind, label, plural, sort_order) VALUES ('work', 'work', 'works', 5);
