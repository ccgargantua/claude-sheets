---
name: sheet
description: "Read, query, edit and format spreadsheet files (.xlsx, .ods, .csv) through the sheet CLI (LibreOffice backend). Use when asked to read, write, append, sort, filter, find, dedupe, format, merge, hide, freeze, chart, add images/comments/links, validate, protect, convert, or manage sheets, rows, columns, named ranges in a spreadsheet file."
---

# Rules

1. `sheet` means `python3 src/sheet.py`. Invoke as `sheet <action> <file> [options]`.
2. Output exactly one command per request. Use `batch` only when the user asks for several changes together or atomically. Use only actions and flags listed below. Never invent flags or actions.
3. Pass only flags the request states or clearly implies. Omit defaults. Never add `--header` unless the user says row 1 is a header. Never add a header or blank row to `--data`.
4. Single-quote JSON and any value with spaces, `=`, `$`, `#`, `!`, `<`, `>`. Use double quotes inside JSON.
5. Flag values follow the flag after a space: `--sheet Sales`, never `--sheet=Sales`.
6. Every file-modifying action accepts `--dry-run` (apply, report, do not save) and `--backup` (save `<file>.bak-<UTC timestamp>` first). Add only when the user asks to preview or back up.

# Disambiguation

- Column width: `col-width` (never `format`). Row height: `row-height`. Fit to content: `autofit`. `format` only styles cells (font, color, fill, border, number format, align).
- `clear` empties cells/formats and keeps layout. `delete-rows`/`delete-cols` remove the rows/cols and shift the rest.
- `hide-*`/`show-*` toggle visibility only. `delete-*` destroys data.
- `filter` returns matching rows (read-only). `find` returns cells containing text. `autofilter` adds dropdown filter buttons to the file.
- `cond-format` styles cells by rule. `format` styles unconditionally.
- `copy-range` keeps source. `move-range` clears source. `fill` extends the first row/col/cell over a range.
- `sort` reorders. `dedupe` removes duplicate rows (edits file).
- `read` returns computed values. `read --formulas` returns formula text. `recalc` hard-recalculates and saves.
- `freeze --cell C3` freezes rows above 3 and columns left of C.

# Actions

Read / query (do not modify)

| action | args |
|---|---|
| info | FILE. Sheets and dimensions |
| read | FILE [--sheet S] [--range A1:C10] [--as json\|csv] [--formulas] |
| find | FILE --query Q [--exact] [--sheet S] |
| filter | FILE --where 'C>100' [--where ...] [--header] [--sheet S]. ops `== != > < >= <= contains`, repeated = AND, e.g. `'B==paid'`, `'A contains foo'` |
| stats | FILE --range R [--sheet S]. count, numeric_count, sum, mean, min, max |
| get-format | FILE --cell A1 [--sheet S]. Font, fill, number format, align, borders, merged, width, height |
| names | FILE. List named ranges |
| charts | FILE [--sheet S]. List charts |

Cells

| action | args |
|---|---|
| write | FILE --cell A1 --value V [--sheet S]. `=...` is a formula |
| write-range | FILE --start A1 --data JSON [--sheet S] |
| append | FILE --data JSON [--sheet S]. After last used row |
| clear | FILE --range R [--what all\|contents\|formats] [--sheet S] |
| copy-range | FILE --src R --dst CELL [--sheet S] [--dst-sheet S2] |
| move-range | FILE --src R --dst CELL [--sheet S] [--dst-sheet S2] |
| fill | FILE --range R [--mode down\|right\|series] [--step N] [--sheet S]. down/right copy first row/col (formulas adjust); series is linear from first cell, `--step` only for series |
| sort | FILE --by COL [--desc] [--header] [--sheet S] |
| dedupe | FILE [--cols A,C] [--header] [--sheet S]. Removes later duplicate rows |
| recalc | FILE |
| merge / unmerge | FILE --range R [--sheet S] |
| hyperlink | FILE --cell A1 --url U [--text T] [--sheet S] |
| comment | FILE --cell A1 --text T [--sheet S] |
| delete-comment | FILE --cell A1 [--sheet S] |

Rows / columns (SPAN: `2:5`, `B:D`, or single `3` / `B`)

| action | args |
|---|---|
| insert-rows / delete-rows | FILE --at N [--count K] [--sheet S] |
| insert-cols / delete-cols | FILE --at COL [--count K] [--sheet S] |
| hide-rows / show-rows | FILE --rows SPAN [--sheet S] |
| hide-cols / show-cols | FILE --cols SPAN [--sheet S] |
| col-width | FILE --col COL --width W [--sheet S]. Characters, 1 char is about 2.3 mm |
| row-height | FILE --rows SPAN --height H [--sheet S]. Points |
| autofit | FILE [--cols SPAN] [--rows SPAN] [--sheet S]. At least one |
| freeze | FILE --cell C3 [--sheet S] |
| unfreeze | FILE [--sheet S] |

Sheets

| action | args |
|---|---|
| create | FILE [--sheets S1,S2] |
| convert | SRC DST. Format from extension |
| add-sheet / delete-sheet | FILE --name N |
| rename-sheet | FILE --name OLD --new-name NEW |
| copy-sheet | FILE --name N --new-name NEW [--position P] |
| move-sheet | FILE --name N --position P. 1-based |
| hide-sheet / show-sheet | FILE --name N |
| protect / unprotect | FILE [--sheet S] [--password P] |
| define-name | FILE --name N --range R [--sheet S]. R may be `Sheet2!A1:B3` |
| delete-name | FILE --name N |

Formatting and data features

| action | args |
|---|---|
| format | FILE --range R [--bold] [--italic] [--underline] [--strike] [--no-bold] [--no-italic] [--no-underline] [--no-strike] [--font-name N] [--font-size N] [--font-color HEX] [--fill HEX] [--number-format F] [--align left\|center\|right] [--valign top\|center\|bottom] [--wrap] [--no-wrap] [--border all\|outline\|top\|bottom\|left\|right\|none] [--border-color HEX] [--sheet S] |
| cond-format | FILE --range R --condition gt\|lt\|ge\|le\|eq\|ne\|between\|contains\|formula --value V [--value2 V2] [--fill HEX] [--font-color HEX] [--bold] [--sheet S]. Needs at least one of fill/font-color/bold |
| cond-format-clear | FILE --range R [--sheet S] |
| validation | FILE --range R --type list\|whole\|decimal\|date\|text-length [--values a,b,c] [--min N] [--max N] [--sheet S]. `--values` only for list |
| validation-clear | FILE --range R [--sheet S] |
| autofilter | FILE --range R [--sheet S]; remove with FILE --off [--sheet S] |

Charts / images

| action | args |
|---|---|
| chart | FILE --range R --type bar\|column\|line\|pie\|scatter\|area --anchor CELL [--title T] [--name N] [--header] [--width-mm W] [--height-mm H] [--sheet S]. `--header` = first range row is series names. Defaults 160x90 mm |
| delete-chart | FILE --name N [--sheet S] |
| image | FILE --path IMG --anchor CELL [--width-mm W] [--height-mm H] [--sheet S] |

Batch

| action | args |
|---|---|
| batch | FILE --ops 'JSON' or FILE --ops-file PATH. One open doc, one save; any op fails, nothing saved. Not allowed inside: batch, create, convert, stop, status. Op keys `file`, `dry_run`, `backup` are rejected |

Op = object with `"action"` plus flag names with `_` for `-`. File is implied. Boolean flags are `true`.

`sheet batch s.xlsx --ops '[{"action":"write","cell":"A1","value":"Hi"},{"action":"format","range":"A1","bold":true},{"action":"col-width","col":"A","width":20}]'`

Daemon

| action | args |
|---|---|
| status | (no file) Running, pid, idle seconds |
| stop | (no file) Stop the LibreOffice daemon |

The daemon starts automatically on first call and exits after 10 idle minutes.

# Notation

- Cells `B7`, ranges `A1:C10`, columns letters, rows 1-based. `--sheet` omitted is the first sheet.
- Auto-typed values: `42` int, `3.5` float, `true`/`false` bool, else text. Formula: `--value '=SUM(A1:A10)'`: Excel syntax, `,` between arguments (never `;`), other sheets as `Sheet2!A1`.
- Colors: hex `FF0000` or `#FF0000`, as given.
- `--data` is a 2D array, rows of cells. One row: `'[["a","b","c"]]'`. Write only the rows the user gave.

# Gotchas

- `.csv` has one sheet and no styling. These fail with `unsupported for csv`: format, get-format, col-width, row-height, autofit, merge, unmerge, hide-rows, show-rows, hide-cols, show-cols, freeze, unfreeze, autofilter, cond-format, cond-format-clear, add-sheet, delete-sheet, rename-sheet, copy-sheet, move-sheet, hide-sheet, show-sheet, protect, unprotect, define-name, delete-name, names, validation, validation-clear, comment, delete-comment, hyperlink, chart, delete-chart, charts, image.
- Output is one JSON object; failure is `{"ok": false, "error": ...}`, exit 1.

# Example

User: "In budget.xlsx on the Q1 sheet, set column A to width 25."

`sheet col-width budget.xlsx --col A --width 25 --sheet Q1`

User: "In budget.xlsx on the Q1 sheet, make A1:D1 bold and set column A to width 25, in one atomic change."

`sheet batch budget.xlsx --ops '[{"action":"format","range":"A1:D1","bold":true,"sheet":"Q1"},{"action":"col-width","col":"A","width":25,"sheet":"Q1"}]'`
