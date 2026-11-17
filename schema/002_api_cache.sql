-- 002_api_cache.sql — remember Open Library responses (milestone M3).
-- Re-running `bookshelf enrich` or adding the same ISBN twice makes no network request,
-- which keeps you well inside Open Library's rate limits and lets enrichment resume.

CREATE TABLE api_cache (
    url         TEXT PRIMARY KEY,
    fetched_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    status      INTEGER NOT NULL CHECK (status BETWEEN 100 AND 599),
    body        TEXT NOT NULL                       -- the response as received
) STRICT, WITHOUT ROWID;
