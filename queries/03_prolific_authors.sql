-- 03: people credited on more than :min_books books, any role.
-- WHERE filters rows before grouping; HAVING filters the groups after.
SELECT a.display_name,
       count(DISTINCT ba.book_id) AS books
FROM authors a
JOIN book_authors ba ON ba.author_id = a.author_id
JOIN active_books b  ON b.book_id    = ba.book_id
GROUP BY a.author_id, a.display_name
HAVING count(DISTINCT ba.book_id) > :min_books
ORDER BY books DESC, a.sort_name;
