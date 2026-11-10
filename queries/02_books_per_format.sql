-- 02: how many editions and copies you hold in each format, including formats with none.
-- Start from the lookup table, not from books: a LEFT JOIN keeps the empty formats,
-- and count(b.book_id) counts only matched rows (count(*) would give empty formats a 1).
SELECT f.format,
       f.label,
       count(b.book_id)           AS editions,
       coalesce(sum(b.copies), 0) AS copies
FROM formats f
LEFT JOIN active_books b ON b.format = f.format
GROUP BY f.format, f.label
ORDER BY f.sort_order;
