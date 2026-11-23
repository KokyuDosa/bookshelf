// Run by tests/test_site_js.py: node tests/js/search.test.mjs <cases.json>
// The cases file holds {"normalize": [[input, expected], ...]} computed by the Python code.
import { readFileSync } from "node:fs";
import {
  normalizeText, prepare, search, toIsbn13, looksLikeIsbn, compareBooks, canonicalBarcode, cleanScan,
} from "../../site/search.js";

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
  { id: 2, title: "Monster Manual", line: "DND 3.5", key: "monster manual dnd 3 5" },
  { id: 3, title: "Monster Manual 3", line: "DND 3.5", key: "monster manual 3 dnd 3 5" },
  { id: 4, title: "One Piece", series: "One Piece", volume: 2, key: "one piece one piece" },
  { id: 5, title: "One Piece", series: "One Piece", volume: 10, key: "one piece one piece" },
  { id: 6, title: "Anathem", authors: ["Neal Stephenson"], key: "anathem neal stephenson" },
  { id: 7, title: "Happiness", series: "Happiness", volume: 1, key: "happiness happiness vol 1 shuzo oshimi" },
  { id: 8, title: "Happiness", series: "Happiness", volume: 7, key: "happiness happiness vol 7 shuzo oshimi" },
  // a line with a numbered series inside it, and a loose book in the same line
  { id: 9, title: "Burnt Offerings", line: "Pathfinder", series: "Rise of the Runelords", volume: 1, key: "burnt offerings pathfinder rise of the runelords vol 1" },
  { id: 10, title: "The Skinsaw Murders", line: "Pathfinder", series: "Rise of the Runelords", volume: 2, key: "the skinsaw murders pathfinder rise of the runelords vol 2" },
  { id: 11, title: "Bestiary", line: "Pathfinder", key: "bestiary pathfinder" },
]);
const ids = r => r.results.map(b => b.id);
check("prefix words", ids(search(books, "hob tolk")), [1]);
check("line and title", ids(search(books, "dnd 3.5 monster")), [2, 3]);
check("whole line", ids(search(books, "pathfinder")), [11, 9, 10]);
// "3" also matches the 3 in "DND 3.5", so both match; the exact title ranks first.
check("exact title first", ids(search(books, "monster manual 3")), [3, 2]);
check("no match", search(books, "dune").results.length, 0);
check("isbn-10 finds isbn-13", ids(search(books, "0-306-40615-2")), [1]);
check("isbn not owned", search(books, "978-0-306-40615-7 ").mode, "isbn");
check("bad check digit", search(books, "0-306-40615-3").mode, "bad-isbn");
check("blank", search(books, "  ").mode, "empty");
check("browse order", [...books].sort(compareBooks).map(b => b.id), [6, 2, 3, 7, 8, 1, 4, 5, 11, 9, 10]);
check("volume number", ids(search(books, "happiness 7")), [8]);
check("vol word", ids(search(books, "happiness vol 7")), [8]);
check("whole series", ids(search(books, "happiness")), [7, 8]);

// Barcodes that aren't ISBNs: the same cases as tests/test_scan.py
for (const [typed, want] of [
  ["070004004007", "0070004004007"], ["0070004004007", "0070004004007"], ["96385074", "96385074"],
  ["9780786928866", "9780786928866"], ["070004004001", null], ["1234", null], ["hello", null],
]) check(`canonicalBarcode(${typed})`, canonicalBarcode(typed), want);
check("price add-on", cleanScan("9780786928866 51995"), "9780786928866");
check("upc add-on", cleanScan("07000400400712"), "070004004007");
const shelf = prepare([{ id: 1, title: "Feng Shui", barcode: "0070004004007", key: "feng shui" },
                       { id: 2, title: "Player's Handbook", isbn: "9780786928866", key: "players handbook" }]);
for (const typed of ["070004004007", "0070004004007", "07000400400712"]) {
  const r = search(shelf, typed);
  check(`barcode ${typed}`, [r.mode, ids(r)], ["barcode", [1]]);
}
check("isbn with add-on", ids(search(shelf, "9780786928866 51995")), [2]);
check("bad upc is just digits", search(shelf, "070004004001").mode, "text");

if (failures.length) {
  console.error(failures.slice(0, 20).join("\n"));
  console.error(`${failures.length} failure(s)`);
  process.exit(1);
}
console.log("ok");
