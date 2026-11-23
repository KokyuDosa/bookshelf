import { compareBooks, normalizeText, prepare, search } from "./search.js";

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
  if (b.line) body.append(el("p", "line", b.line)); // product line, e.g. "DND 3.5"
  body.append(el("h3", "title", b.subtitle ? `${b.title}: ${b.subtitle}` : b.title));
  if (b.series) {
    // Manga often has series and title the same ("Happiness"): then show just the volume.
    const same = normalizeText(b.series) === normalizeText(b.title);
    const text = b.volume == null ? b.series : same ? `Vol. ${b.volume}` : `${b.series} · Vol. ${b.volume}`;
    body.append(el("p", "series", text));
  }
  if (b.contents) {
    // A set's pieces, indented under its title: "Vol. 1", "Vol. 2", "Slipcase"
    const list = el("ul", "parts");
    list.setAttribute("aria-label", "In this set");
    for (const part of b.contents) list.append(el("li", null, part));
    body.append(list);
  }
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
    setStatus("browse", null, activeTag ? `${plural(pool.length, "book")} tagged ${activeTag}` : `All ${plural(pool.length, "book")}, A to Z by line, series and title`);
    render([...pool].sort(compareBooks));
  } else if (result.mode === "bad-isbn") {
    setStatus("miss", "That isn’t a valid ISBN", "The check digit doesn’t match. Check the number and try again.");
    render([]);
  } else if (!result.results.length) {
    const detail = result.mode === "isbn"
      ? `No book with ISBN ${result.isbn}${where}.`
      : result.mode === "barcode"
      ? `No book with barcode ${result.barcode}${where}.`
      : `No title, line, series or author matches “${query.trim()}”${where}.`;
    setStatus("miss", "Not in the collection", detail);
    render([]);
  } else if (result.mode === "isbn" || result.mode === "barcode") {
    setStatus("hit", "In the collection", result.isbn ? `ISBN ${result.isbn}` : `Barcode ${result.barcode}`);
    render(result.results);
  } else {
    setStatus("count", null, `${plural(result.results.length, "book")} match${result.results.length === 1 ? "es" : ""} “${query.trim()}”${where}`);
    render(result.results);
  }

  const params = new URLSearchParams(location.search);
  if (query.trim()) params.set("q", query.trim()); else params.delete("q");
  if (activeTag) params.set("tag", activeTag); else params.delete("tag");
  const qs = params.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

function buildTags() {
  const counts = new Map();
  for (const b of books) for (const t of b.tags || []) counts.set(t, (counts.get(t) || 0) + 1);
  if (counts.size < 2) return;
  // Every genre, most-used first; the row scrolls sideways on a phone.
  const all = [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  // ?tag=math opens the list filtered, so a link can share one genre
  const wanted = new URLSearchParams(location.search).get("tag");
  activeTag = all.find(([t]) => wanted && normalizeText(t) === normalizeText(wanted))?.[0] ?? null;
  const press = () => {
    for (const c of tagBox.children) c.setAttribute("aria-pressed", String(c.dataset.tag === (activeTag ?? "")));
  };
  const chip = (label, tag) => {
    const b = el("button", "chip", label);
    b.type = "button";
    b.dataset.tag = tag ?? "";
    b.addEventListener("click", () => {
      activeTag = activeTag === tag ? null : tag; // tapping the chosen genre again shows all
      press();
      run();
    });
    return b;
  };
  tagBox.append(chip("All", null), ...all.map(([t, n]) => chip(`${t} ${n}`, t)));
  press();
  tagBox.hidden = false;
  tagBox.querySelector('[aria-pressed="true"]')?.scrollIntoView({ inline: "center", block: "nearest" });
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
