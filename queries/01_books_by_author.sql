-- 01: every book by one author: series books first (by series, then position in it),
-- then standalone books by year. Parameter :author_key is an authors.match_key.
-- In the sqlite3 shell:  .param set :author_key "'le guin ursula k'"
SELECT b.book_id,
       b.title,
       s.name        AS series,
       b.series_index,
       b.pub_year,
       ba.role
FROM authors a
JOIN book_authors ba ON ba.author_id = a.author_id
JOIN active_books b  ON b.book_id    = ba.book_id
LEFT JOIN series s   ON s.series_id  = b.series_id
WHERE a.match_key = :author_key
ORDER BY s.name IS NULL,        -- false (0) sorts first, so series books lead
         s.name,
         b.series_index,
         b.pub_year,
         b.sort_title;
