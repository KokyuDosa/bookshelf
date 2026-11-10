-- 06: how SQLite runs query 01. Every table should be reached by SEARCH (an index or
-- primary-key lookup), never SCAN. book_authors is found through book_authors_author;
-- drop that index and this plan turns into a full scan of the link table.
EXPLAIN QUERY PLAN
SELECT b.book_id, b.title, s.name, b.series_index, b.pub_year, ba.role
FROM authors a
JOIN book_authors ba ON ba.author_id = a.author_id
JOIN active_books b  ON b.book_id    = ba.book_id
LEFT JOIN series s   ON s.series_id  = b.series_id
WHERE a.match_key = :author_key
ORDER BY s.name IS NULL, s.name, b.series_index, b.pub_year, b.sort_title;
