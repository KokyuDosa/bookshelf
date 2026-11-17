// Search logic for the phone page. Pure functions, no DOM, so Node can test them.
// normalizeText must give the same result as bookshelf.normalize.normalize_text in Python:
// tests/test_site_js.py checks the two against shared and randomly generated cases.

const APOSTROPHES = new Set(["'", "’", "‘", "ʼ"]);
const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u;
const DROPPED_MARK = /[\p{Mn}\p{Me}]/u;

// Python's str.casefold() goes further than toLowerCase() for a few letters.
function caseFold(s) {
  return s.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ").replace(/ſ/g, "s");
}

export function normalizeText(s) {
  const folded = caseFold(s.replace(/&/g, " and ")).normalize("NFKD");
  let out = "";
  for (const ch of folded) {
    if (APOSTROPHES.has(ch) || DROPPED_MARK.test(ch)) continue;
    out += LETTER_OR_DIGIT.test(ch) ? ch : " ";
  }
  return out.split(" ").filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- ISBN

export function cleanIsbn(text) {
  return text.replace(/^\s*isbn(?:-?1[03])?:?/i, "").replace(/[\s\-‐-―−]/g, "").toUpperCase();
}

export function looksLikeIsbn(text) {
  const s = cleanIsbn(text);
  return /^\d{13}$/.test(s) || /^\d{9}[\dX]$/.test(s);
}

function check13(first12) {
  let total = 0;
  for (let i = 0; i < 12; i++) total += Number(first12[i]) * (i % 2 === 0 ? 1 : 3);
  return String((10 - (total % 10)) % 10);
}

function check10(first9) {
  let total = 0;
  for (let i = 0; i < 9; i++) total += Number(first9[i]) * (10 - i);
  const c = (11 - (total % 11)) % 11;
  return c === 10 ? "X" : String(c);
}

// Returns the ISBN-13, or null when the check digit or prefix is wrong.
export function toIsbn13(text) {
  const s = cleanIsbn(text);
  if (/^\d{9}[\dX]$/.test(s)) {
    if (check10(s.slice(0, 9)) !== s[9]) return null;
    const core = "978" + s.slice(0, 9);
    return core + check13(core);
  }
  if (/^(978|979)\d{10}$/.test(s) && check13(s.slice(0, 12)) === s[12]) return s;
  return null;
}

// ---------------------------------------------------------------- search

// Each word of the query must be the start of some word in the book's key, so
// "hob tolk" finds "The Hobbit" by Tolkien and "dnd 3.5 mon" finds Monster Manual.
export function prepare(books) {
  for (const b of books) {
    b._words = b.key.split(" ");
    b._title = normalizeText(b.title);
    b._sort = sortKey(b.title);
    b._seriesSort = b.series ? sortKey(b.series) : "";
  }
  return books;
}

// Like Python's title_key: one leading article dropped, so "The Strange RPG" sorts under S.
function sortKey(text) {
  const key = normalizeText(text);
  const [first, ...rest] = key.split(" ");
  return ["the", "a", "an"].includes(first) && rest.length ? rest.join(" ") : key;
}

function score(book, tokens, phrase) {
  let total = 0;
  for (const t of tokens) {
    let best = 0;
    for (const w of book._words) {
      if (w === t) { best = 3; break; }
      if (w.startsWith(t)) best = 2;
    }
    if (!best) return 0;
    total += best;
  }
  if (book._title === phrase) total += 10;
  else if (book._title.startsWith(phrase)) total += 5;
  return total;
}

export function search(books, query) {
  const raw = query.trim();
  if (!raw) return { mode: "empty", results: [] };
  if (looksLikeIsbn(raw)) {
    const isbn = toIsbn13(raw);
    if (!isbn) return { mode: "bad-isbn", results: [] };
    return { mode: "isbn", isbn, results: books.filter(b => b.isbn === isbn) };
  }
  const phrase = normalizeText(raw);
  const tokens = phrase.split(" ").filter(Boolean);
  if (!tokens.length) return { mode: "empty", results: [] };
  const hits = [];
  for (const b of books) {
    const s = score(b, tokens, phrase);
    if (s) hits.push([s, b]);
  }
  hits.sort((a, b) => b[0] - a[0] || compareBooks(a[1], b[1]));
  return { mode: "text", results: hits.map(h => h[1]) };
}

// Browse order: series together and in volume order, then by title.
export function compareBooks(a, b) {
  const ka = a._seriesSort || a._sort, kb = b._seriesSort || b._sort;
  if (ka !== kb) return ka.localeCompare(kb);
  if ((a.volume ?? 0) !== (b.volume ?? 0)) return (a.volume ?? 0) - (b.volume ?? 0);
  return a._sort.localeCompare(b._sort);
}
