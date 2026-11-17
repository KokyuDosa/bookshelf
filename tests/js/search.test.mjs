// Run by tests/test_site_js.py: node tests/js/search.test.mjs <cases.json>
// The cases file holds {"normalize": [[input, expected], ...]} computed by the Python code.
import { readFileSync } from "node:fs";
import { normalizeText, prepare, search, toIsbn13, looksLikeIsbn, compareBooks } from "../../site/search.js";

const failures = [];
const check = (label, actual, expected) => {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) failures.push(`${label}: got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`);
};

const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
for (const [input, expected] of cases.normalize) check(`normalizeText(${JSON.stringify(input)})`, normalizeText(input), expected);
for (const [input, expected] of cases.isbn) check(`toIsbn13(${JSON.stringify(input)})`, toIsbn13(input), expected);
for (const [input, expected] of cases.looks_like_isbn) check(`looksLikeIsbn(${JSON.stringify(input)})`, looksLikeIsbn(input), expected);

const books = prepare([
  { id: 1, title: "The Hobbit", authors: ["J.R.R. Tolkien"], isbn: "9780306406157", key: "the hobbit j r r tolkien" },
  { id: 2, title: "Monster Manual", series: "DND 3.5", key: "monster manual dnd 3 5" },
  { id: 3, title: "Monster Manual 3", series: "DND 3.5", key: "monster manual 3 dnd 3 5" },
  { id: 4, title: "One Piece", series: "One Piece", volume: 2, key: "one piece one piece" },
  { id: 5, title: "One Piece", series: "One Piece", volume: 10, key: "one piece one piece" },
  { id: 6, title: "Anathem", authors: ["Neal Stephenson"], key: "anathem neal stephenson" },
]);
const ids = r => r.results.map(b => b.id);
check("prefix words", ids(search(books, "hob tolk")), [1]);
check("series and title", ids(search(books, "dnd 3.5 monster")), [2, 3]);
// "3" also matches the 3 in "DND 3.5", so both match; the exact title ranks first.
check("exact title first", ids(search(books, "monster manual 3")), [3, 2]);
check("no match", search(books, "dune").results.length, 0);
check("isbn-10 finds isbn-13", ids(search(books, "0-306-40615-2")), [1]);
check("isbn not owned", search(books, "978-0-306-40615-7 ").mode, "isbn");
check("bad check digit", search(books, "0-306-40615-3").mode, "bad-isbn");
check("blank", search(books, "  ").mode, "empty");
check("browse order", [...books].sort(compareBooks).map(b => b.id), [6, 2, 3, 1, 4, 5]);

if (failures.length) {
  console.error(failures.slice(0, 20).join("\n"));
  console.error(`${failures.length} failure(s)`);
  process.exit(1);
}
console.log("ok");
