# Using bookshelf

Run everything from the project folder in the VS Code terminal, with the virtual environment active.
Your site's address will be **https://kokyudosa.github.io/bookshelf/** (repository name `bookshelf`).

## One-time website setup

1. On GitHub: repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. Bring your database up to date and publish:

```powershell
bookshelf migrate          # adds the Open Library cache table (schema version 2)
bookshelf enrich           # optional: years, pages, publishers and covers for books with ISBNs
bookshelf publish
```

3. Watch the **Actions** tab: the workflow runs the tests, then deploys. Open the address on your
   phone and use **Add to Home Screen** so it opens like an app.

## Everyday commands

| To | Run |
| --- | --- |
| Check whether you own something | `bookshelf search hollow earth` or `bookshelf search 978-1-4243-0829-3` |
| Add a book by its barcode number | `bookshelf add 9781421534466` |
| Add a game book | `bookshelf add 9780786928866 --line "DND 3.5"` |
| Add a manga volume | `bookshelf add 9781421534466 --series "One Piece" --volume 52 --tag Manga` |
| Add an omnibus | `bookshelf add --title "Berserk Deluxe Edition" --series "Berserk Deluxe" --volume 1 --edition Omnibus --format hardcover` |
| Add a book with no ISBN | `bookshelf add --title "The Time Machine" --author "H. G. Wells" --year 1895` |
| Add a translation or anthology | `--author`, `--translator`, `--editor`, `--illustrator`, in credit order |
| See or fix one book | `bookshelf show 56`, `bookshelf edit 56 --clear isbn` (see below) |
| Add a slipcase or boxed set | `bookshelf add 9781568823348 --format "box set" --part "Vol. 1" --part "Vol. 2" --part Slipcase` (see below) |
| Change many books at once | `bookshelf edit-many --title-has "call of cthulhu" --line "Call of Cthulhu"` (see below) |
| Count a second copy | `bookshelf add 9780786928866 --another-copy` |
| Keep a book off the website | add `--hidden` |
| Record its value (private) | add `--value 45.00` |
| Fill in details from Open Library | `bookshelf enrich` (re-runs are free: answers are cached) |
| Search a volume of a series | `bookshelf search happiness 7` or `happiness vol 7`; the website works the same way |
| Recompute matching keys after an update changes the rules | `bookshelf rekey` |
| Import a CSV export (another MyStuff2 category, say) | `bookshelf import data\imports\Manga.csv --dry-run`, then without `--dry-run` (see below) |
| See what needs attention | `bookshelf review`, then `bookshelf review --resolve 1 ignored` |
| Update the website | `bookshelf publish` |

## Importing a CSV export

Use this for another MyStuff2 category, or for a fresh export of one you've already imported.
Keep export files in `data\imports\`: that folder is private and never reaches GitHub.

1. **Export from MyStuff2** with the same settings as before: header row on, comma delimiter,
   double-quote text delimiter, `|` as the multi-value delimiter, media off. A single `.csv`,
   a `.tsv`, or a `.zip` holding several category CSVs all work. Excel `.xlsx` files don't, so
   export as CSV.
2. **Try it first.** A dry run does everything except save, and reports what would happen:

   ```powershell
   bookshelf import data\imports\Manga.csv --dry-run
   ```

   It prints rows read; how many books would be inserted, updated, left unchanged or rejected;
   the books it would flag for review; and warnings such as a column missing from the file.
3. **Import for real** with the same command without `--dry-run`. A backup of your database
   is written to `data\backups\` first.
4. **Deal with what's left over.**
   - `bookshelf review` lists flagged books: a barcode that isn't an ISBN, a condition word
     the mapping doesn't know, a value that isn't a number, or a possible duplicate. Fix the book
     with `bookshelf edit`, then close the flag with `bookshelf review --resolve <number> ignored`
     (or `distinct` / `merged` for duplicates).
   - Rows that can't become a book at all (no item ID, no title) are listed with the reason in
     `data\imports\rejects-<file>-<time>.csv`.
5. **Fill in and publish:** `bookshelf enrich` for the new books with ISBNs, then
   `bookshelf publish`.

### What the importer does with your rows

- **Matching:** every row is matched by its MyStuff2 item ID, so importing the same file twice
  never creates duplicates. Unchanged rows are skipped, so your `bookshelf edit` fixes stay. A
  row you have *changed in MyStuff2* overwrites the fields it fills in (empty cells never erase
  anything), so make fixes in bookshelf, not MyStuff2.
- **What counts as changed:** only the columns the mapping reads (title, author, genre, price
  and so on). Exporting with or without images, or a newer "item updated" time, changes
  nothing. That makes it safe to import a full-collection export over a category you imported
  before: the books already in the database are reported as unchanged.
- **Books you already have:** a row whose ISBN you already own, for example one added by hand,
  only fills that book's empty fields; it doesn't add a second copy of the book.
- **Titles:** store-listing extras are peeled off the end of a title:

  | In the title | Becomes |
  | --- | --- |
  | `DND 3.5; Monster Manual` | product line "DND 3.5", title "Monster Manual" |
  | `(2 Copies)` | 2 copies |
  | `(Hardcover)`, `- Hardcover`, `Box Set` | the format |
  | `(Edition 2)`, `(2nd Edition)` | edition "2nd", if the edition cell is empty |
  | `(0786931345)` | the ISBN, if the barcode cell is empty and it's a valid ISBN |
  | `by Douglas R. Hofstadter` | cut off; it becomes the author if the author cell is empty |
  | `Illustrated by Don Lawrence` | an illustrator credit (also "Translated by", "Edited by") |
  | `Prophet Volume 1: Remission` | series "Prophet", vol. 1, title "Remission" (also `Vol. IV`, `(Vol. 2: …)`) |

  Each rule only removes text it recognises and never empties a title. A "by …" that isn't
  plainly names ("by Jeff, McArtor, Mike") stays in the title; names taken from a title are
  flagged as `check_credits` so you can check them in `bookshelf review`. The volume rule only
  applies when there's no volume column or value. The settings are under `[title_rules]` in
  the mapping file.
- **Years:** a year in the edition cell becomes the book's year ("1st; 1973" is edition 1st,
  year 1973; "October 1952" is year 1952), and so does one after the publisher ("MacMillan,
  New York, 1968" is publisher MacMillan, year 1968).
- **Roles:** in the author cell, `(ed.)`, `(trans.)` or `(ill.)` after a name sets the role, for
  example `Fray Baroque (ed.)|Tegan Eanelli (ed.)`. Use it in corrections.
- **Volumes:** the `volume` column sets the volume number ("3", "03", "Vol. 3", "v3" and "2.5"
  all work). A volume without a series makes the title the series, so ten rows titled
  "Happiness" with volumes 1 to 10 become volumes 1 to 10 of the series "Happiness". A title that
  repeats its volume ("Happiness, Vol. 3") is trimmed to "Happiness". Something that isn't one
  number, such as "1-3" for an omnibus, is flagged for review, and you set it with
  `bookshelf edit <number> --volume 1 --edition Omnibus`. Categories without a `volume` column
  get a one-line note on import, nothing more.
- **Same title, different volume:** the duplicate check compares line, series, volume, title,
  first author and year, so volumes 1 to 10 of "Happiness" are never flagged as duplicates of each
  other. Importing volume 3 twice under different item IDs is.
- **Genres** become tags.

### Teaching it new values

These live in `config\mappings\mystuff2.toml`. A re-import only touches rows that changed *in
the export*, so after editing the mapping, re-apply it with `--remap`:

```powershell
bookshelf import data\imports\Books.csv --remap --dry-run
```

`--remap` overwrites every field the export fills, including fixes you made with `edit` or
`edit-many` (a trimmed title goes back to the export's title, for example), so check the
dry run first. Fields the export doesn't fill, such as a line you set by hand, are kept.

- **A new condition word** (say "Near Mint"): add it under `[condition_values]`, for example
  `"near mint" = "excellent"`.
- **Two spellings of one publisher:** add the variant under `[publisher_aliases]`, for example
  `"Viz Media LLC" = "VIZ Media"`.

### Fixing one row before it's imported

For a row with junk in it, such as a title copied from a store listing, add an entry to
`data\imports\mystuff2-corrections.toml`, then import again. The entry is keyed by the
MyStuff2 item ID (the `item id` column, or the "imported from" line of `bookshelf show`), and
each line replaces that column's cell in the export:

```toml
# Necromancer D20 Sourcebook Wurst Of Grimtooth's Traps
["0A1B2C3D-0000-0000-0000-000000000000"]
title = "Wurst of Grimtooth's Traps"
publisher = "Necromancer Games"
price = "$49.99"
```

The file already holds the 11 fixes made to your TTRPG export; they follow the same pattern.
MyStuff2 exports co-authors alphabetically by first name, so a correction is also the way to
put them in cover order: `author = "Gilles Deleuze|Félix Guattari"`.

### Importing from something other than MyStuff2

Copy `config\mappings\mystuff2.toml` to a new name, such as `config\mappings\mylist.toml`, and
change three things:

- `source`: a name for where the books came from, e.g. `"mylist"`.
- `key_column`: a column holding a unique, unchanging ID for each row. This is required, because
  it's how re-imports avoid duplicates. For a spreadsheet you made yourself, add an ID column
  (1, 2, 3…).
- The column names under `[fields]`.

Then import with `--mapping`:

```powershell
bookshelf import data\imports\mylist.csv --mapping mylist --dry-run
```

Its corrections file is `data\imports\mylist-corrections.toml`. A mapping can fill title,
authors, publisher, tags, pages, edition, condition, estimated_value, isbn, line, series and
volume. A `line` column wins over a `Line; Title` title.
There's no separate year or format column yet.

If your manga category calls its column something other than `volume` (MyStuff2 uses your
attribute names), change `volume = "volume"` in `config\mappings\mystuff2.toml` to match.

## Looking at and fixing one book

`search` prints each book's number. `show` and `edit` take that number, an ISBN in any form,
or words from the title (put several words in quotes for `edit`). In PowerShell write `56`,
not `#56`: a `#` starts a comment there.

| To | Run |
| --- | --- |
| See every stored value, private ones included | `bookshelf show 56` |
| The same as JSON | `bookshelf show 56 --json` |
| Remove a wrong ISBN | `bookshelf edit 56 --clear isbn` |
| Correct it | `bookshelf edit 56 --isbn 0-7869-2893-X` |
| Fix several things at once | `bookshelf edit 56 --year 2003 --publisher "Wizards of the Coast" --condition "very good"` |
| Replace the credits (order kept) | `bookshelf edit 56 --author "Skip Williams" --author "Jonathan Tweet" --editor "Kim Mohan"` |
| Move into a series | `bookshelf edit "berserk deluxe" --series "Berserk Deluxe" --volume 1` |
| Put into a product line | `bookshelf edit 56 --line "DND 3.5"` |
| Cut a prefix off the title | `bookshelf edit 56 --trim-title "Call of Cthulhu:"` |
| Tags | `bookshelf edit 56 --add-tag Classics --remove-tag TTRPG` |
| Private details | `--value 120`, `--price 45`, `--notes "Signed"`, `--loaned-to Sam --loaned-on 2026-11-01` |
| What's in a set | `--add-part "Vol. 1"`, `--missing-part 3`, `--found-part 3`, `--remove-part 3` (see below) |
| Empty any field | `--clear FIELD` (repeatable): isbn, line, series, volume, authors, tags, parts, value, loan, … |
| Gave it away or sold it | `bookshelf edit 56 --remove` (today) or `--remove 2026-11-17` |
| Changed your mind | `bookshelf edit 56 --restore` |

`edit` prints each change as `old -> new` and asks before saving (`--yes` skips the question).
Anything it refuses changes nothing. Clears happen before sets, so `--clear series --series X`
moves a book in one go. A removed book stays in the database with its history, drops out of
searches and the website, and is never re-added by a re-import. Edits survive re-importing an
unchanged MyStuff2 export, because unchanged rows are skipped.

### Lines and series

A **product line** groups books that belong together without an order: "DND 3.5",
"Call of Cthulhu", "Shadowrun 5E". A **series** is numbered: "Rise of the Runelords" 1 to 6,
"Happiness" vol. 7. A book can have both (a Pathfinder adventure path is in the line
"Pathfinder" and a series). Keep the edition in the line's name ("DND 3.5", not "DND" plus an
edition), because the website groups and sorts by the name.

### Slipcase and boxed sets

A set with one ISBN is one book: that's what you scan, buy, sell and value. List what's inside
it as **parts**, in order:

```powershell
bookshelf edit 9781568823348 --title "Malleus Monstrorum" --format "box set" `
    --add-part "Vol. 1: Monsters of the Mythos" --add-part "Vol. 2: Deities of the Mythos" `
    --add-part Slipcase
```

(The backtick at the end of a line continues a PowerShell command on the next line.)

- **Several works in one volume:** list each as a `work` part, so every title is searchable:
  `--add-part "work: Human, All Too Human" --add-part "work: Beyond Good and Evil"`.
- **Kinds:** each part has a kind (work, volume, booklet, handouts, map, screen, cards, dice,
  slipcase, other), guessed from its name: "Vol. 2" is a volume, "Keeper Screen" a screen. To
  choose it yourself, put it first with a colon: `--add-part "handouts: Keeper's materials"`.
- **Numbers:** `bookshelf show` lists the parts numbered 1, 2, 3…; the other options use those
  numbers. Removing a part renumbers the ones after it.
- **Missing pieces:** `--missing-part 4` marks part 4 as gone, `--found-part 4` undoes it. Only
  you see this (in `show`); the website lists what the set contains, not what you're missing.
- **Searching** matches part names too, so "deities of the mythos" finds the set, here and on
  the website.
- `bookshelf add` takes `--part` (repeatable) for a new set. `edit-many` can't change parts,
  because they belong to one book.
- Two books bought separately, each with its own ISBN, are not a set: give them a series and
  volume numbers instead.

## Changing many books at once

`edit-many` chooses books with filters, then makes the same change to each of them. It lists
every change, asks once, and saves all of them or none: if one book refuses (say, a loan date
without a borrower), nothing is saved and it tells you which book.

```powershell
# Every book with "Call of Cthulhu" in its title goes into that line, and loses the prefix
bookshelf edit-many --title-has "call of cthulhu" --line "Call of Cthulhu" --trim-title "Call of Cthulhu:"
```

Choosing books (give at least one; several must all match):

| Filter | Chooses |
| --- | --- |
| `--title-has WORDS` | these words, next to each other, in the title (case and accents ignored, whole words) |
| `--match QUERY` | what `bookshelf search QUERY` finds (title, subtitle, line, series, authors) |
| `--in-line NAME`, `--in-series NAME` | books in that line or series |
| `--has-tag TAG` | books with that tag; repeat to need several |
| `--from-publisher NAME` | books from that publisher |
| `--no-isbn` | books without an ISBN |
| `--ids 3,5,9-12` | those book numbers |
| `--except 7,8` | leaves those numbers out |
| `--all` | every book |
| `--include-removed` | also books you've marked removed |

The changes are the same as `edit`'s, except the ones that only make sense for one book:
`--title`, `--isbn`, `--volume`, `--cover` and `--ol-key`. Useful ones:

| To | Add |
| --- | --- |
| Set the line or series | `--line "DND 3.5"`, `--series "Rise of the Runelords"` |
| Cut a prefix off each title | `--trim-title "Call of Cthulhu:"` (any case; `:` `;` `-` or a space after it all work; a title that would end up empty is left alone) |
| Tags | `--add-tag Horror`, `--remove-tag TTRPG` |
| Shelf, condition, format, publisher | `--shelf "Office 3"`, `--condition good`, `--format hardcover`, `--publisher Chaosium` |
| Empty a field | `--clear line`, `--clear shelf`, … |

- `--dry-run` shows the changes and saves nothing. Without `--yes`, it asks before saving.
- Only the first 50 changed books are listed; `--show 500` lists more.
- Options can't be shortened for `edit-many` (`--title` is not `--title-has`), so a typo is an
  error rather than a different filter.
- A later re-import leaves these changes alone unless the row changed in MyStuff2 or you use
  `--remap`.

## Adding: details

`add` shows what it found and asks before saving; `--yes` skips the question. With an ISBN it
asks Open Library for the details, and anything you type as an option wins over what it finds.
Use `--offline` to skip the lookup. Formats: hardcover, trade paperback, mass market, paperback,
box set, ebook, audiobook, other. Conditions: mint, like new, excellent, very good, good, fair, poor.

`search` exits with status 0 when you own a match, 1 when you don't and 2 for an invalid ISBN,
so scripts can use it.

## What the website shows

Title, subtitle, product line, series and volume, a set's contents, authors, edition, format, publisher, year, ISBN, number of
copies, tags and the Open Library cover. Never: values, prices, notes, loans, shelf, condition,
books added with `--hidden`, or books you've removed. Friends can download the same list as a
CSV from the bottom of the page.

The genre buttons under the search box show every genre with its number of books, most used
first; tap one to show only that genre, tap it again to show everything. A search and a genre
combine. Both end up in the page's address, so you can share them as a link:
`…/bookshelf/?q=shadowrun`, `…/bookshelf/?tag=Math` or `…/bookshelf/?tag=Philosophy&q=badiou`.

## Open Library

Lookups identify themselves to Open Library and stay under one request a second. To be allowed
three a second, set your email as contact details (sent only to Open Library):

```powershell
$env:BOOKSHELF_CONTACT = "you@example.com"                                   # this terminal only
[Environment]::SetEnvironmentVariable("BOOKSHELF_CONTACT", "you@example.com", "User")  # permanently
```
