# Using bookshelf

Run every command from the project folder in the VS Code terminal, with the virtual environment
active: the prompt shows `(.venv)`, or run `.venv\Scripts\Activate.ps1`. Your website is
**https://kokyudosa.github.io/bookshelf/**.

Every command explains its options with `--help`, for example `bookshelf edit --help`.

- [Quick reference](#quick-reference)
- [Finding books](#finding-books)
- [Adding books](#adding-books): scanning, `add`
- [Fixing books](#fixing-books): `show`, `edit`, lines, series and sets, `edit-many`, `review`
- [Importing a CSV export](#importing-a-csv-export)
- [The website](#the-website): `publish`, `export`
- [Open Library](#open-library): `enrich`
- [Upkeep](#upkeep): updating, backups, files, other commands, troubleshooting

## Quick reference

| To | Run |
| --- | --- |
| Check whether you own something | `bookshelf search hollow earth` or `bookshelf search 978-1-4243-0829-3` |
| List a genre, or search inside one | `bookshelf search --tag Math`, `bookshelf search badiou --tag Philosophy` |
| See your genres | `bookshelf tags` |
| See everything about one book | `bookshelf show 56` |
| Add a stack of books, scanned or typed | `bookshelf scan`, then scan or type ISBNs |
| Add a run of one series | `bookshelf scan --tag Manga --series "Kaiju No. 8"` |
| Add one book by ISBN | `bookshelf add 9781421534466` |
| Add a book with no ISBN | `bookshelf add --title "The Time Machine" --author "H. G. Wells" --year 1895` |
| Count a second copy | `bookshelf add 9780786928866 --another-copy` |
| Fix one book | `bookshelf edit 56 --year 2003`, `bookshelf edit 56 --clear isbn` |
| Change many books at once | `bookshelf edit-many --title-has "call of cthulhu" --line "Call of Cthulhu"` |
| See what needs attention | `bookshelf review` |
| Import a MyStuff2 export | `bookshelf import data\imports\Manga.csv --dry-run`, then without `--dry-run` |
| Fill in years, pages and covers | `bookshelf enrich` |
| Update the website | `bookshelf publish` |

## Finding books

```powershell
bookshelf search hollow earth          # words from the title, subtitle, line, series, authors or a set's contents
bookshelf search happiness 7           # volume 7 of a series ("happiness vol 7" works too)
bookshelf search 0-7869-2886-0         # an ISBN-10 or ISBN-13, hyphens or not
bookshelf search 070004004007          # a stored UPC or store code
bookshelf search --tag Math            # every book in a genre, A to Z
bookshelf search badiou --tag Philosophy
bookshelf search --tag Philosophy --tag Politics   # books with both genres
bookshelf tags                         # your genres, with how many books each
```

- Every word you type must start a word of the book, so `hob tolk` finds *The Hobbit* by
  Tolkien. Case and accents don't matter.
- Results show each book's number, which `show` and `edit` use. At most 25 are listed;
  `--limit 100` lists more.
- Hidden books are included, but removed ones aren't.
- The exit status is 0 when you own a match, 1 when you don't and 2 for an invalid ISBN, so
  scripts can use it.
- **Genres (tags):** `--tag` keeps only books with that genre; repeat it to need several. On its
  own it lists the whole genre in A-to-Z order (by line, then series and volume, then title).
  - Case, accents and a plural don't matter: `--tag "graphic novels"` finds Graphic Novel.
  - A name that isn't one of your genres gets suggestions: `No genre called 'sci'. Did you mean:
    Science Fiction, Computer Science, Science?`
  - Genre names aren't matched by plain search words, so `bookshelf search history` still looks
    for "history" in titles, not every History book.
- **`bookshelf tags`** lists your genres with their number of books, most used first
  (`--by-name` for A to Z). Removed books aren't counted.
- The website's search box follows the same rules, and its genre buttons work like `--tag`.

## Adding books

### Scanning a stack

A USB barcode scanner types the code and presses Enter, like a keyboard, so `bookshelf scan`
turns the terminal into a scanning station. Scan one book after another; each new book is saved
straight away. Without a scanner, type the ISBNs instead: hyphens, spaces and ISBN-10s are
fine, and a typo is caught by the check digit.

```powershell
bookshelf scan
bookshelf scan --shelf "Office 3" --tag Philosophy     # applied to every book this session
bookshelf scan --tag Manga --series "Kaiju No. 8"      # one series, volume by volume
```

```
scan> 9780786928866
  Added #240  Player's Handbook — Jonathan Tweet, Monte Cook, Skip Williams — 2003
scan> 9781568823348
  Already have #14 Call of Cthulhu; Malleus Monstrorum (1 copy). Type + if this is another copy.
scan> q
Done: added 1, 1 you already had.
```

While scanning, type:

| Type | To |
| --- | --- |
| `u` | undo the last thing saved (a book, a copy or a barcode); repeat to go further back |
| `+` | count another copy of the book just scanned |
| `?` | list these commands |
| `q` (or Ctrl+C) | finish; it prints what the session did |

- **Details** come from Open Library.
  - When Open Library doesn't know a book, you're asked for its title and authors.
  - Press Enter on the title to save the book for later instead. It's saved as "ISBN 978…",
    hidden from the website, with a `needs_details` flag in `bookshelf review`.
  - Fill it in later with `bookshelf edit <number> --title "…" --author "…" --public`.
- **Barcodes that aren't ISBNs** include the UPC on an older paperback's cover and a store code
  on a game book.
  - You're asked for the ISBN from the copyright page, or the title. Either way, the barcode is
    saved on the book, so scanning it again finds the book.
  - A UPC scanned for a book you already have is saved onto that book.
- **Price add-ons** (the small extra barcode beside the main one) are ignored if your scanner
  sends them.
- **Problems beep**: an unknown book, one you already have, or a bad code. `--quiet` turns the
  beep off.
- **No connection?** If Open Library can't be reached, the session carries on without it and
  asks for titles. `--offline` does that from the start.
- **Genres** are suggested from Open Library's subjects, but only genres you already use (a tag
  on at least one book) or give with `--tag`. A suggestion never creates a new genre. Suggested
  genres are listed under the book (`genres from Open Library: Science Fiction`);
  `--no-genres` turns this off. To teach it Open Library's wording ("Mathematics" for your
  "Math"), see [Teaching it new values](#teaching-it-new-values).
- **`--series`** puts every book in that series. Each volume number is read from Open Library's
  title ("Kaiju No. 8, Vol. 3" becomes title "Kaiju No. 8", vol. 3) or subtitle ("Vol. 3").
  When there's none, you're asked:

  ```
    Volume in Kaiju No. 8 [4]:
  ```

  Press Enter to take the suggestion (one after the last volume this session), type a number
  (`2.5` works), or `-` for none. Undoing a book with `u` also takes back its number.
- **Options for the whole session:** `--shelf`, `--tag` (repeatable), `--line`, `--series`,
  `--condition`, `--format` and `--hidden`.
- **Fixing a mistake:** `u` takes back the last book. After the session, `bookshelf edit
  <number>` fixes one book, and `bookshelf edit-many --ids 241-250 …` fixes the same thing on
  several.

**Setting up the scanner:**
1. Plug it in and scan a book into Notepad. It should type the digits and start a new line.
2. If it doesn't press Enter after each code, turn on its "Enter suffix" (or "CR suffix") by
   scanning the setup barcode in its manual.
3. Keep the terminal window in front while scanning.

### One at a time: `add`

```powershell
bookshelf add 9780786928866 --line "DND 3.5"
bookshelf add 9781421534466 --series "One Piece" --volume 52 --tag Manga
bookshelf add --title "Berserk Deluxe Edition" --series "Berserk Deluxe" --volume 1 --edition Omnibus --format hardcover
bookshelf add 9781568823348 --format "box set" --part "Vol. 1" --part "Vol. 2" --part Slipcase
```

With an ISBN, `add` asks Open Library for the details. Anything you give as an option wins over
what it finds. It then shows the book and asks before saving.

- Genres are suggested the same way as in [scanning](#scanning-a-stack), only from genres you
  already use, and shown before you confirm.
- With `--series` but no `--volume`, the volume is read from Open Library's title, as in
  scanning.

- If you already own the ISBN, it says so instead of adding a second copy. Add `--another-copy`
  to count one more.
- If the book looks like one you already have (same title, author and year), it warns you and
  flags it for review.

| Option | What it sets |
| --- | --- |
| `--title`, `--subtitle` | the title, if there's no ISBN or you want a different one |
| `--author`, `--editor`, `--translator`, `--illustrator` | credits, in the order you give them; repeat each for several people |
| `--line`, `--series`, `--volume` | product line, numbered series and volume number (see [Lines, series and sets](#lines-series-and-sets)) |
| `--edition` | e.g. `2nd`, `Omnibus`, `Gold Edition` |
| `--part` | a piece of a set, e.g. `"Vol. 1"`, `Slipcase`; repeat in order |
| `--barcode` | a UPC or store code that isn't the ISBN |
| `--publisher`, `--year`, `--pages` | publication details |
| `--format` | hardcover, trade paperback, mass market, paperback, box set, ebook, audiobook, other |
| `--condition` | mint, like new, excellent, very good, good, fair, poor |
| `--copies`, `--shelf` | how many you own and where they live (the shelf is never published) |
| `--tag` | a genre or label; repeat for several |
| `--value` | estimated value, e.g. `45.00` (private) |
| `--hidden` | keep it off the website |
| `--another-copy` | if you already own this ISBN, count one more copy |
| `--no-genres` | don't add genres suggested from Open Library's subjects |
| `--offline` | don't ask Open Library |
| `--yes` | save without asking |

## Fixing books

### One book: `show` and `edit`

Both take a book's number (from `search`), an ISBN in any form, or words from the title.
For `edit`, put several words in quotes. In PowerShell, write `56` rather than `#56`, because
`#` starts a comment.

```powershell
bookshelf show 56                # every stored value, private ones and review flags included
bookshelf show 56 --json         # the same as JSON
```

| To | Run |
| --- | --- |
| Fix several things at once | `bookshelf edit 56 --year 2003 --publisher "Wizards of the Coast" --condition "very good"` |
| Correct or remove the ISBN | `bookshelf edit 56 --isbn 0-7869-2893-X`, `bookshelf edit 56 --clear isbn` |
| Store a cover UPC | `bookshelf edit 56 --barcode 070004004007` |
| Replace the credits (order kept) | `bookshelf edit 56 --author "Skip Williams" --author "Jonathan Tweet" --editor "Kim Mohan"` |
| Put into a line or series | `bookshelf edit 56 --line "DND 3.5"`, `bookshelf edit "berserk deluxe" --series "Berserk Deluxe" --volume 1` |
| Cut a prefix off the title | `bookshelf edit 56 --trim-title "Call of Cthulhu:"` |
| Tags | `bookshelf edit 56 --add-tag Classics --remove-tag TTRPG` |
| What's in a set | `--add-part "Vol. 1"`, `--remove-part 3`, `--missing-part 3`, `--found-part 3` |
| Private details | `--value 120`, `--price 45`, `--notes "Signed"`, `--loaned-to Sam --loaned-on 2026-11-01`, `--acquired 2024-06-01` |
| Other details | `--subtitle`, `--edition`, `--format`, `--pages`, `--copies`, `--shelf`, `--language`, `--cover URL`, `--ol-key OL7353617M` |
| Hide from the website, or show again | `--hidden`, `--public` |
| Gave it away or sold it | `bookshelf edit 56 --remove` (today) or `--remove 2026-11-17` |
| Changed your mind | `bookshelf edit 56 --restore` |
| Empty a field | `--clear FIELD`, repeatable: `isbn`, `barcode`, `line`, `series`, `volume`, `authors`, `tags`, `parts`, `value`, `price`, `loan`, `notes`, `shelf`, … (`--help` lists them all) |

- `edit` prints each change as `old -> new` and asks before saving; `--yes` skips the question.
- If it refuses anything, nothing changes.
- Clears happen before sets, so `--clear series --series X` moves a book in one go.
- A removed book stays in the database with its history. It drops out of searches and the
  website, and a re-import never adds it back.

### Lines, series and sets

- **Product line:** books that belong together without an order, such as "DND 3.5",
  "Call of Cthulhu" or "Shadowrun 5E". Keep the edition in the name ("DND 3.5", not "DND"
  plus an edition), because the website groups and sorts by the name.
- **Series:** books in a numbered order, such as "Rise of the Runelords" 1 to 6 or "Happiness"
  vol. 7. A volume number needs a series. A book can have both a line and a series (a
  Pathfinder adventure path is in the line "Pathfinder" and in a series).
- **Set:** a slipcase or boxed set with one ISBN is one book, because that's what you scan, buy,
  sell and value. List what's inside it as **parts**, in order:

  ```powershell
  bookshelf edit 9781568823348 --title "Malleus Monstrorum" --format "box set" `
      --add-part "Vol. 1: Monsters of the Mythos" --add-part "Vol. 2: Deities of the Mythos" `
      --add-part Slipcase
  ```

  (A backtick at the end of a line continues a PowerShell command on the next line.)
  - **Kinds:** each part has a kind (work, volume, booklet, handouts, map, screen, cards, dice,
    slipcase, other), guessed from its name: "Vol. 2" is a volume, "Keeper Screen" a screen.
    To choose the kind yourself, put it first with a colon: `--add-part "handouts: Keeper's materials"`.
  - **Several works in one volume:** list each as a `work` part, so every title is searchable:
    `--add-part "work: Human, All Too Human" --add-part "work: Beyond Good and Evil"`.
  - **Numbers:** `show` numbers the parts 1, 2, 3…, and `--remove-part`, `--missing-part` and
    `--found-part` use those numbers. Removing a part renumbers the ones after it.
  - **Missing pieces:** these are private. The website lists what a set contains, not what you're
    missing.
  - **Separate books:** two books bought separately, each with its own ISBN, aren't a set. Give
    them a series and volume numbers instead.

### Many books: `edit-many`

`edit-many` chooses books with filters, then makes the same change to each of them. It lists
every change, asks once, and saves all of them or none. If one book refuses (say, a loan date
without a borrower), nothing is saved and it tells you which book.

```powershell
# Every book with "Call of Cthulhu" in its title goes into that line and loses the prefix
bookshelf edit-many --title-has "call of cthulhu" --line "Call of Cthulhu" --trim-title "Call of Cthulhu:" --dry-run
```

Choosing books (give at least one filter; when you give several, a book must match all of them):

| Filter | Chooses |
| --- | --- |
| `--title-has WORDS` | these words, next to each other, in the title (whole words; case and accents ignored) |
| `--match QUERY` | what `bookshelf search QUERY` finds |
| `--in-line NAME`, `--in-series NAME` | books in that line or series |
| `--has-tag TAG` | books with that tag; repeat to need several |
| `--from-publisher NAME` | books from that publisher |
| `--no-isbn` | books without an ISBN |
| `--ids 3,5,9-12`, `--except 7,8` | those book numbers; leave these out |
| `--all` | every book |
| `--include-removed` | also books you've marked removed |

- **Changes** are the same as `edit`'s, except the ones that belong to one book only: `--title`,
  `--isbn`, `--barcode`, `--volume`, `--cover`, `--ol-key` and the part options.
- **`--trim-title`** accepts any case, and `:`, `;`, `-` or a space after the prefix. A title
  that would end up empty is left alone.
- **Credit options** (`--author` and the others) replace the credits of every chosen book, so
  use them with care.
- **`--dry-run`** shows the changes and saves nothing. Without `--yes`, it asks before saving.
- **`--show 500`** lists more changed books; only the first 50 are listed by default.
- **Options can't be shortened** for `edit-many` (`--title` doesn't mean `--title-has`), so a typo
  is an error rather than a different filter.

### The review list: `review`

Imports, `add` and `scan` flag books that need a look instead of guessing. `bookshelf review`
lists the open flags with a number, the book and the reason:

| Reason | Means |
| --- | --- |
| `possible_duplicate` | same line, series, volume, title, first author and year as another book |
| `invalid_isbn` | the barcode cell was neither an ISBN nor a UPC; the book was imported without it |
| `unknown_condition` | a condition word the mapping doesn't know |
| `bad_value` | a number that isn't one: pages, value or volume |
| `check_credits` | names were taken from the title ("… by Douglas R. Hofstadter"); check them |
| `check_title` | the title may still contain names the importer couldn't separate |
| `needs_details` | a scanned book saved for later; give it a title and `--public` |

Fix the book with `edit` if needed, then close the flag with
`bookshelf review --resolve <flag number> <how>`:

| How | Use it when |
| --- | --- |
| `ignored` | you've dealt with it, or it's fine as it is (every reason except duplicates) |
| `distinct` | the two books really are different, e.g. two editions |
| `merged` | it was the same book twice and you've combined them |

Closing a flag only records your answer; it changes no book. To merge two books, do it first:
copy any missing details onto the one you keep, then `--copies 2` if you really own two, or
`--remove` the duplicate. A closed flag stays closed, and a re-import doesn't raise it again.
`show` lists a book's flags with how each was resolved.

## Importing a CSV export

Use this for a MyStuff2 category you haven't imported yet, or for a fresh export of one you have.
Keep export files in `data\imports\`: that folder is private and never reaches GitHub.

1. **Export from MyStuff2** with the same settings as before: header row on, comma delimiter,
   double-quote text delimiter, `|` as the multi-value delimiter, media off. A `.csv`, a `.tsv`
   or a `.zip` of several category CSVs all work. Excel `.xlsx` files don't, so export as CSV.
2. **Try it first.** A dry run does everything except save:

   ```powershell
   bookshelf import data\imports\Manga.csv --dry-run
   ```

   It reports rows read, how many books would be inserted, updated, left unchanged or rejected,
   the books it would flag for review, and warnings such as a missing column.
3. **Import for real** with the same command without `--dry-run`. Your database is backed up to
   `data\backups\` first.
4. **Deal with what's left over.** Run `bookshelf review` (see [the review list](#the-review-list-review)).
   Rows that can't become a book at all (no item ID, no title) are listed with the reason in
   `data\imports\rejects-<file>-<time>.csv`.
5. **Fill in and publish:** `bookshelf enrich`, then `bookshelf publish`.

### What the importer does with your rows

- **Matching:** every row is matched by its MyStuff2 item ID, so importing the same file twice
  never creates duplicates. A row whose ISBN you already own (one you added by hand, say) only
  fills that book's empty fields.
- **Your fixes are kept:** unchanged rows are skipped, so changes made with `edit`, `edit-many`
  or `scan` stay put.
  - A row you've changed *in MyStuff2* overwrites the fields it fills. Empty cells never erase
    anything, but make fixes in bookshelf, not MyStuff2.
  - Only the columns the mapping reads count as changes. Exporting with or without images, or a
    newer "item updated" time, changes nothing, so a full-collection export can go over
    categories you've already imported.
- **Titles:** store-listing extras are peeled off the end of a title:

  | In the title | Becomes |
  | --- | --- |
  | `DND 3.5; Monster Manual` | product line "DND 3.5", title "Monster Manual" |
  | `(2 Copies)` | 2 copies |
  | `(Hardcover)`, `- Hardcover`, `Box Set` | the format |
  | `(Edition 2)`, `(2nd Edition)` | edition "2nd", if the edition cell is empty |
  | `(0786931345)` | the ISBN, if the barcode cell is empty and it's a valid ISBN |
  | `by Douglas R. Hofstadter` | cut off; becomes the author if the author cell is empty |
  | `Illustrated by Don Lawrence` | an illustrator credit (also "Translated by", "Edited by") |
  | `Prophet Volume 1: Remission` | series "Prophet", vol. 1, title "Remission" (also `Vol. IV`, `(Vol. 2: …)`) |

  - Each rule only removes text it recognises, and never empties a title.
  - A "by …" that isn't plainly names ("by Jeff, McArtor, Mike") stays in the title and is
    flagged `check_title`. Names that are taken out are flagged `check_credits`.
  - The volume rule only applies when there's no volume column or value.
- **Volumes:** the `volume` column sets the volume number ("3", "03", "Vol. 3", "v3" and "2.5"
  all work).
  - A volume without a series makes the title the series: ten rows titled "Happiness" with
    volumes 1 to 10 become volumes 1 to 10 of the series "Happiness".
  - A title that repeats its volume ("Happiness, Vol. 3") is trimmed to "Happiness".
  - A value that isn't a single number (such as "1-3" for an omnibus) is flagged `bad_value`.
    Set it with `bookshelf edit <number> --volume 1 --edition Omnibus`.
  - A category without a `volume` column gets a one-line note, nothing more.
- **Years:** a year in the edition cell becomes the book's year ("1st; 1973" is edition 1st,
  year 1973; "October 1952" is year 1952). So does a year after the publisher ("MacMillan,
  New York, 1968" is publisher MacMillan, year 1968).
- **Barcodes:** a barcode cell that's a UPC rather than an ISBN is kept as the book's barcode.
- **Roles:** in the author cell, `(ed.)`, `(trans.)` or `(ill.)` after a name sets the role,
  e.g. `Fray Baroque (ed.)|Tegan Eanelli (ed.)`. This is mostly useful in corrections.
- **Duplicates:** the check compares line, series, volume, title, first author and year. So
  volumes 1 to 10 of "Happiness" never count as duplicates of each other, but volume 3 imported
  twice under different item IDs does.
- **Genres** become tags.

### Teaching it new values

The rules live in `config\mappings\mystuff2.toml`:

- **A new condition word** ("Near Mint", say): add it under `[condition_values]`, e.g.
  `"near mint" = "excellent"`.
- **Two spellings of one publisher:** add the variant under `[publisher_aliases]`, e.g.
  `"Viz Media LLC" = "VIZ Media"`.
- **Title rules:** each rule can be switched on or off under `[title_rules]`.
- **Genre suggestions:** `config\genre_aliases.toml` maps Open Library's subject wording to your
  genres, e.g. `"Mathematics" = "Math"`. A line naming a genre you don't use does nothing until
  you do.
- **A differently named column:** if your manga category calls its volume column something else
  (MyStuff2 uses your attribute names), change `volume = "volume"` under `[fields]` to match.

A normal re-import only touches rows that changed *in the export*. To apply new mapping rules to
the rows you already have, add `--remap`:

```powershell
bookshelf import data\imports\Books.csv --remap --dry-run
```

`--remap` overwrites every field the export fills, including fixes you made with `edit` or
`edit-many` (a trimmed title goes back to the export's title, for example), so check the dry run
first. Fields the export doesn't fill, such as a line or parts you set yourself, are kept.

### Fixing a row before it's imported

For a row with junk in it, add an entry to `data\imports\mystuff2-corrections.toml` and import
again. Each entry is keyed by the MyStuff2 item ID (the `item id` column, or the "imported from"
line of `bookshelf show`). Each line under it replaces that column's cell:

```toml
# Necromancer D20 Sourcebook Wurst Of Grimtooth's Traps
["0A1B2C3D-0000-0000-0000-000000000000"]
title = "Wurst of Grimtooth's Traps"
publisher = "Necromancer Games"
price = "$49.99"
```

Corrections are also how you put co-authors in cover order: MyStuff2 exports them alphabetically
by first name. For example, `author = "Gilles Deleuze|Félix Guattari"`. Use `--corrections FILE`
to use a different corrections file.

### Importing from something other than MyStuff2

Copy `config\mappings\mystuff2.toml` to a new name, such as `config\mappings\mylist.toml`, and
change three things:

- `source`: a name for where the books came from, e.g. `"mylist"`.
- `key_column`: a column with a unique, unchanging ID for each row. It's required, because it's
  how re-imports avoid duplicates. For a spreadsheet you made yourself, add an ID column
  (1, 2, 3…).
- The column names under `[fields]`. A mapping can fill title, authors, publisher, tags, pages,
  edition, condition, estimated_value, isbn, line, series and volume. There's no year, format
  or shelf column yet.

```powershell
bookshelf import data\imports\mylist.csv --mapping mylist --dry-run
```

Its corrections file is `data\imports\mylist-corrections.toml`.

## The website

### One-time setup

1. On GitHub: repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. Run `bookshelf publish`, then watch the **Actions** tab: the workflow runs the tests, then
   deploys.
3. Open the site on your phone and use **Add to Home Screen** so it opens like an app.

### Publishing: `publish`

`bookshelf publish` updates the website in one go:

1. It writes the public list to `site\data\books.json` and `site\data\books.csv`.
2. If anything changed since the last publish, it runs the tests and shows a summary, e.g.
   "237 books: 12 added, 3 changed, 0 removed". It asks, then commits those two files and pushes.
3. It waits while GitHub tests and deploys the site (usually under a minute), showing each step,
   and tells you whether the website actually updated:

   ```
   Waiting for GitHub to test and deploy (Ctrl+C stops waiting, not GitHub)…
     test: ok
     build: ok
     deploy: ok
   The website is up to date: https://kokyudosa.github.io/bookshelf/
   ```

   If the deploy fails, it names the failed step and asks whether to try again. Many failures
   are hiccups on GitHub's side, and a second try fixes them. If it fails again, run
   `gh run view <run> --log-failed` (it prints the exact command) to see why.

Step 3 happens even when there's nothing new to publish, so `publish` also tells you whether the
*last* deploy got through. Checking needs the GitHub CLI (`gh`), logged in; without it,
`publish` says so and you check the Actions tab yourself.

| Option | Does |
| --- | --- |
| `--yes` | don't ask before committing, and retry a failed deploy without asking |
| `--no-tests` | skip the test run |
| `--no-push` | commit but don't push (push later with `git push`) |
| `--no-wait` | push without waiting for GitHub's deploy |
| `--check` | don't publish; just check the last deploy, and offer to retry it if it failed |

`publish` commits only the book list. When you change the code itself (after an update, say),
commit and push that yourself; see [Updating bookshelf](#updating-bookshelf).

`bookshelf export` writes the same two files without testing, committing or pushing, so you can
look at them first. Use `--out FOLDER` to write them somewhere else.

### What the website shows

- **Shown:** title, subtitle, product line, series and volume, a set's contents, authors,
  edition, format, publisher, year, ISBN, other barcode, number of copies, tags and the Open
  Library cover.
- **Never shown:** values, prices, notes, loans, shelf, condition, missing set pieces, books
  marked `--hidden`, and books you've removed.
- **Download:** friends can download the list as a CSV from the bottom of the page.
- **Search:** the search box works like `bookshelf search`, and takes an ISBN or a stored UPC
  too.
- **Genres:** the buttons under the search box show every genre with its number of books, most
  used first.
  - Tap one to show only that genre; tap it again to show everything.
  - A search and a genre combine.
- **Sharing:** both end up in the page's address, so you can share them as links:
  `…/bookshelf/?q=shadowrun`, `…/bookshelf/?tag=Math` or
  `…/bookshelf/?tag=Philosophy&q=badiou`.

## Open Library

`bookshelf enrich` fills in missing details for books with an ISBN:

- **What it fills:** publisher, year, pages, cover and Open Library key, plus authors for books
  that have none.
- **What it keeps:** it never overwrites a value you've set, and it doesn't change titles.
- **Caching:** answers are cached in the database, so a re-run is quick and only asks Open
  Library about books it hasn't asked about before. `--limit 50` stops after 50 books.

`add` and `scan` use the same lookups, and also use Open Library's subjects to suggest genres. Lookups identify themselves to Open Library and stay
under one request a second. To be allowed three a second, set your email as contact details
(sent only to Open Library):

```powershell
$env:BOOKSHELF_CONTACT = "you@example.com"                                             # this terminal only
[Environment]::SetEnvironmentVariable("BOOKSHELF_CONTACT", "you@example.com", "User")  # permanently
```

## Upkeep

### Updating bookshelf

When you get a new version of the code (a zip to unzip over the project, say):

```powershell
pytest                   # everything should pass
bookshelf migrate        # upgrades the database if the new version needs it; backs it up first
bookshelf rekey          # only when the update notes say so: recomputes matching keys
git add -A
git commit -m "Update bookshelf"
git push
bookshelf publish
```

`bookshelf migrate` is safe to run any time: if the database is already current, it says so and
does nothing. The everyday commands (`add`, `scan`, `edit`, `search`, `publish` and the rest)
refuse to run on an out-of-date database and tell you to migrate. `import` doesn't check, so
migrate before importing.

### Backups

- **When they're made:** `migrate` and `import` (not `--dry-run`) copy your database into
  `data\backups\` first, named like `books-v6-20261123T211500Z.db` (schema version and time,
  in UTC).
- **Restoring:** close anything using the database, then copy a backup over it:

  ```powershell
  Copy-Item data\backups\books-v6-20261123T211500Z.db data\books.db
  ```

- **Off-computer copies:** `data\` never goes to GitHub, so to keep a copy elsewhere, copy
  `data\books.db` to another drive or a cloud folder now and then.

### Your files

| Where | What | On GitHub? |
| --- | --- | --- |
| `data\books.db` | your database | no |
| `data\backups\` | automatic backups | no |
| `data\imports\` | exports, corrections (they can hold prices), reject lists | no |
| `config\mappings\` | import mappings | yes |
| `site\` | the website; `site\data\` holds the published list | yes |
| `schema\` | database migrations | yes |
| `docs\` | this guide (`usage.md`) and the record of design decisions (`decisions.md`) | yes |

### Other commands

| Command | Does |
| --- | --- |
| `bookshelf init` | creates a new, empty database (refuses if one exists) |
| `bookshelf seed` | builds a sample database of tricky test books in `data\sample.db` (`--out` for another file) |
| `bookshelf --db data\sample.db search …` | runs any command on another database; `--db` goes before the command |
| `bookshelf snapshot` | regenerates `schema\snapshot.sql`, which the tests compare against (after writing a migration) |

### Troubleshooting

| Problem | Fix |
| --- | --- |
| `bookshelf` isn't recognized | the virtual environment isn't active: run `.venv\Scripts\Activate.ps1` |
| "run 'bookshelf migrate'" | the code is newer than your database: run `bookshelf migrate` |
| `edit #56` does nothing | `#` starts a PowerShell comment: write `edit 56` |
| "Nothing to publish" | the website already shows this collection |
| The website hasn't changed after publishing | run `bookshelf publish --check`: it says whether the last deploy failed and can retry it. If it got through, reload; your phone may show the old page for a few minutes |
| "Couldn't check the deploy" | `gh` isn't logged in: run `gh auth login` |
| A scanner types digits but nothing happens | it isn't sending Enter: turn on its Enter (CR) suffix |
