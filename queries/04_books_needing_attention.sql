-- 04: books with no ISBN, or with nobody credited. NOT EXISTS is an anti-join:
-- it keeps the rows for which the subquery finds nothing.
SELECT b.book_id,
       b.title,
       b.isbn13 IS NULL AS missing_isbn,
       NOT EXISTS (SELECT 1 FROM book_authors ba WHERE ba.book_id = b.book_id) AS missing_credits
FROM active_books b
WHERE b.isbn13 IS NULL
   OR NOT EXISTS (SELECT 1 FROM book_authors ba WHERE ba.book_id = b.book_id)
ORDER BY b.sort_title;
