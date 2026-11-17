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
| Add a manga volume | `bookshelf add 9781421534466 --series "One Piece" --volume 52 --tag Manga` |
| Add an omnibus | `bookshelf add --title "Berserk Deluxe Edition" --series "Berserk Deluxe" --volume 1 --edition Omnibus --format hardcover` |
| Add a book with no ISBN | `bookshelf add --title "The Time Machine" --author "H. G. Wells" --year 1895` |
| Count a second copy | `bookshelf add 9780786928866 --another-copy` |
| Keep a book off the website | add `--hidden` |
| Record its value (private) | add `--value 45.00` |
| Fill in details from Open Library | `bookshelf enrich` (re-runs are free: answers are cached) |
| See what needs attention | `bookshelf review`, then `bookshelf review --resolve 1 ignored` |
| Update the website | `bookshelf publish` |

`add` shows what it found and asks before saving; `--yes` skips the question. With an ISBN it
asks Open Library for the details, and anything you type as an option wins over what it finds.
Use `--offline` to skip the lookup. Formats: hardcover, trade paperback, mass market, paperback,
box set, ebook, audiobook, other. Conditions: mint, like new, excellent, very good, good, fair, poor.

`search` exits with status 0 when you own a match, 1 when you don't and 2 for an invalid ISBN,
so scripts can use it.

## What the website shows

Title, subtitle, series and volume, authors, edition, format, publisher, year, ISBN, number of
copies, tags and the Open Library cover. Never: values, prices, notes, loans, shelf, condition,
books added with `--hidden`, or books you've removed. Friends can download the same list as a
CSV from the bottom of the page, and you can share a search as a link: `…/bookshelf/?q=shadowrun`.

## Open Library

Lookups identify themselves to Open Library and stay under one request a second. To be allowed
three a second, set your email as contact details (sent only to Open Library):

```powershell
$env:BOOKSHELF_CONTACT = "you@example.com"                                   # this terminal only
[Environment]::SetEnvironmentVariable("BOOKSHELF_CONTACT", "you@example.com", "User")  # permanently
```
