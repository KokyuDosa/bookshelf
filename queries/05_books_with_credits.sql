-- 05: one row per book with its people in credited order, roles marked when not 'author'.
-- ORDER BY inside an aggregate needs SQLite 3.44+ (any current Python bundles newer).
SELECT b.book_id,
       b.title,
       group_concat(
           a.display_name || CASE ba.role WHEN 'author' THEN '' ELSE ' (' || ba.role || ')' END,
           '; ' ORDER BY ba.position
       ) AS credits
FROM active_books b
LEFT JOIN book_authors ba ON ba.book_id  = b.book_id
LEFT JOIN authors a       ON a.author_id = ba.author_id
GROUP BY b.book_id, b.title
ORDER BY b.sort_title;
