import { compareBooks, prepare, search } from "./search.js";

const PAGE_SIZE = 60;
const $ = sel => document.querySelector(sel);
const input = $("#q");
const statusBox = $("#status");
const list = $("#results");
const moreButton = $("#more");
const tagBox = $("#tags");

let books = [];
let current = [];
let shown = 0;
let activeTag = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function editionLabel(edition) {
  return /^\d+(st|nd|rd|th)$/i.test(edition) ? `${edition} edition` : edition;
}

function bookItem(b) {
  const li = el("li", "book");
  if (b.cover) {
    const img = el("img", "cover");
    img.src = b.cover;
    img.alt = "";
    img.loading = "lazy";
    img.decoding = "async";
    img.addEventListener("error", () => img.remove());
    li.append(img);
  }
  const body = el("div", "body");
  body.append(el("h3", "title", b.subtitle ? `${b.title}: ${b.subtitle}` : b.title));
  if (b.series) body.append(el("p", "series", b.volume != null ? `${b.series} · Vol. ${b.volume}` : b.series));
  if (b.authors) body.append(el("p", "authors", b.authors.join(", ")));
  const meta = [b.edition && editionLabel(b.edition), b.format, b.year].filter(Boolean);
  if (meta.length || b.copies > 1) {
    const line = el("p", "meta", meta.join(" · "));
    if (b.copies > 1) line.append(el("span", "copies", `${b.copies} copies`));
    body.append(line);
  }
  li.append(body);
  return li;
}

function setStatus(kind, heading, detail) {
  statusBox.className = `status ${kind}`;
  statusBox.replaceChildren();
  if (heading) statusBox.append(el("strong", null, heading));
  if (detail) statusBox.append(el("span", null, detail));
}

function render(results) {
  current = results;
  shown = 0;
  list.replaceChildren();
  showMore();
}

function showMore() {
  const next = current.slice(shown, shown + PAGE_SIZE);
  list.append(...next.map(bookItem));
  shown += next.length;
  moreButton.hidden = shown >= current.length;
  moreButton.textContent = `Show ${Math.min(PAGE_SIZE, current.length - shown)} more`;
}

function plural(n, word) {
  return `${n.toLocaleString()} ${word}${n === 1 ? "" : "s"}`;
}

function run() {
  const query = input.value;
  const pool = activeTag ? books.filter(b => b.tags?.includes(activeTag)) : books;
  const result = search(pool, query);
  const where = activeTag ? ` in ${activeTag}` : "";

  if (result.mode === "empty") {
    setStatus("browse", null, activeTag ? `${plural(pool.length, "book")} tagged ${activeTag}` : `All ${plural(pool.length, "book")}, A to Z by series and title`);
    render([...pool].sort(compareBooks));
  } else if (result.mode === "bad-isbn") {
    setStatus("miss", "That isn’t a valid ISBN", "The check digit doesn’t match. Check the number and try again.");
    render([]);
  } else if (!result.results.length) {
    const detail = result.mode === "isbn"
      ? `No book with ISBN ${result.isbn}${where}.`
      : `No title, series or author matches “${query.trim()}”${where}.`;
    setStatus("miss", "Not in the collection", detail);
    render([]);
  } else if (result.mode === "isbn") {
    setStatus("hit", "In the collection", `ISBN ${result.isbn}`);
    render(result.results);
  } else {
    setStatus("count", null, `${plural(result.results.length, "book")} match${result.results.length === 1 ? "es" : ""} “${query.trim()}”${where}`);
    render(result.results);
  }

  const params = new URLSearchParams(location.search);
  if (query.trim()) params.set("q", query.trim()); else params.delete("q");
  const qs = params.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function buildTags() {
  const counts = new Map();
  for (const b of books) for (const t of b.tags || []) counts.set(t, (counts.get(t) || 0) + 1);
  if (counts.size < 2) return;
  const top = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 14);
  const chip = (label, tag) => {
    const b = el("button", "chip", label);
    b.type = "button";
    b.setAttribute("aria-pressed", String(activeTag === tag));
    b.addEventListener("click", () => {
      activeTag = tag;
      for (const c of tagBox.children) c.setAttribute("aria-pressed", String(c === b));
      run();
    });
    return b;
  };
  tagBox.append(chip("All", null), ...top.map(([t, n]) => chip(`${t} ${n}`, t)));
  tagBox.hidden = false;
}

function footer(data) {
  $("#count").textContent = plural(data.count, "book");
  if (data.as_of) {
    const date = new Date(data.as_of);
    $("#as-of").textContent = `updated ${date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}`;
  }
}

let timer = 0;
input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 80); });
input.form.addEventListener("submit", e => { e.preventDefault(); run(); input.blur(); });
moreButton.addEventListener("click", showMore);

async function load() {
  try {
    // no-cache: always check for a newer list, but reuse the download when unchanged
    const res = await fetch("data/books.json", { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    books = prepare(data.books);
    footer(data);
    buildTags();
    input.value = new URLSearchParams(location.search).get("q") || "";
    run();
  } catch {
    setStatus("miss", "Couldn’t load the book list", "Check your connection and reload the page.");
  }
}

load();
