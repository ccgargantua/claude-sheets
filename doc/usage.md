# Usage

Invocation and action list: [README](../README.md), [sheet skill](../.claude/skills/sheet/SKILL.md). Below: what the code outputs and enforces.

- [Output envelope](#output-envelope)
- [Output shapes](#output-shapes)
- [Values: computed vs formulas](#values-computed-vs-formulas)
- [Auto-typing](#auto-typing)
- [--dry-run and --backup](#--dry-run-and---backup)
- [Batch](#batch)
- [Units](#units)
- [CSV limits](#csv-limits)
- [Per-format behavior](#per-format-behavior)
- [Action semantics](#action-semantics)
- [Limits and security](#limits-and-security)

## Output envelope

Success: `{"ok": true, ...}`, exit 0. Failure: `{"ok": false, "error": "<msg>"}`, exit 1 (also argparse errors; unexpected exceptions as `"<ExceptionType>: <msg>"`). One JSON object, UTF-8, `ensure_ascii=false`.

## Output shapes

Fields after `ok`. `sheet` is the resolved sheet name (default: first sheet).

**Read / query (never save)**

| action | fields |
|---|---|
| info | `file`, `format`, `size` (bytes), `sheets`: `[{name, rows, cols}]` (used extent) |
| read | `sheet`, `range` (null if empty), then `data` (2D, empty = `null`) or with `--as csv` `csv` (string) |
| find | `sheet`, `count`, `matches`: `[{cell, value}]` |
| filter | `sheet`, `header` (only with `--header`), `count`, `rows`: `[{row, values}]` (`row` = 1-based sheet row) |
| stats | `sheet`, `range`, `count` (non-empty), `numeric_count`, `sum` (0 if none), `mean`/`min`/`max` (null if none) |
| get-format | `sheet`, `cell`, `font` `{name,size,bold,italic,underline,strike,color}`, `fill`, `number_format`, `align`, `valign`, `wrap`, `borders` `{top,bottom,left,right}` (each null or `{color,width_mm}`), `merged` (false or range), `col_width` (chars), `row_height` (points). Unset `fill`/`font.color` = null |
| names | `count`, `names`: `[{name, range}]` (`range` like `Sheet1!A1:B3`) |
| charts | `count`, `charts`: `[{sheet, name, type, range, anchor}]` |
| status | `running`, `pid`, `idle_seconds` (null when not running) |

**Cells and data**

| action | fields |
|---|---|
| write | `sheet`, `cell` |
| write-range | `sheet`, `range` |
| append | `sheet`, `row` (first row written), `range` |
| clear | `sheet`, `range`, `what` |
| copy-range, move-range | `sheet`, `src`, `dst_sheet`, `dst` |
| fill | `sheet`, `range`, `mode` |
| sort | `sheet`, `by` (uppercased), `desc` |
| dedupe | `sheet`, `removed` (count) |
| recalc | `recalculated` (true) |
| hyperlink | `sheet`, `cell`, `url` |
| comment, delete-comment | `sheet`, `cell` |
| merge | `sheet`, `merged` |
| unmerge | `sheet`, `unmerged` (count of merged areas split) |
| format | `sheet`, `range`, `applied` (sorted option names, e.g. `["bold","fill","no_wrap"]`) |
| cond-format | `sheet`, `range`, `condition` |
| cond-format-clear | `sheet`, `range` |
| validation | `sheet`, `range`, `type` |
| validation-clear | `sheet`, `range` |

**Rows / columns**

| action | fields |
|---|---|
| insert-rows, delete-rows | `sheet`, `at`, `count` |
| insert-cols, delete-cols | `sheet`, `at` (uppercased letter), `count` |
| hide-rows, show-rows | `sheet`, `rows` (`"first:last"`), `visible` |
| hide-cols, show-cols | `sheet`, `cols` (`"first:last"` as column numbers), `visible` |
| col-width | `sheet`, `col` (uppercased), `width` |
| row-height | `sheet`, `rows` (`"first:last"`), `height` |
| autofit | `sheet`, plus `cols` and/or `rows` (`"first:last"`) as requested |
| freeze | `sheet`, `frozen_rows`, `frozen_cols` |
| unfreeze | `sheet` |
| autofilter | on: `sheet`, `autofilter` true, `range`; off: `sheet`, `autofilter` false, `removed` (count) |

**Sheets and names**

| action | fields |
|---|---|
| create | `file`, `sheets` |
| add-sheet, delete-sheet, rename-sheet, copy-sheet, move-sheet | `sheets` (names after change) |
| hide-sheet, show-sheet | `sheets`, `hidden` (names of hidden sheets) |
| protect, unprotect | `sheet`, `protected` (bool) |
| define-name | `name`, `range` (`Sheet!A1:B3`) |
| delete-name | `name` |
| convert | `src`, `dst`, `sheets`, plus `skipped_sheets` when dst is csv and src had more than one sheet |

**Charts, images, daemon, batch**

| action | fields |
|---|---|
| chart | `sheet`, `name`, `type`, `range`, `anchor` |
| delete-chart | `sheet`, `name` |
| image | `sheet`, `anchor`, `width_mm`, `height_mm` (final size) |
| stop | `stopped` (true if a daemon was running) |
| batch | `count`, `results` (one object per op, same shape as the standalone action), plus `dry_run`/`backup` |

## Values: computed vs formulas

- `read` (and `find`, `filter`, `stats`, `dedupe`) see **computed** values. `read --formulas` returns formula text (`=SUM(A1:A3)`) for formula cells, plain values elsewhere.
- Formulas are written and read as Excel-style English text with `,` argument separators; `;` gives `Err:508`.
- Whole numbers come back as ints (`3`, not `3.0`).
- Date/time-formatted cells read as ISO strings (`2024-01-31`, `2024-01-31T10:00:00`, `10:00:00`). Boolean-formatted cells read as `true`/`false`. Cells in error read as their error text (e.g. `#DIV/0!`).
- `recalc` hard-recalculates and saves.

## Auto-typing

`write --value` only; `--data` keeps JSON types. Checked in order:

| input | stored as |
|---|---|
| empty string | empty cell |
| starts with `=` | formula |
| `true`/`false` (any case) | boolean |
| integer `[+-]?(0\|[1-9]\d*)` | number |
| decimal/exponent (`3.5`, `.5`, `1e3`) | number |
| anything else, incl. leading-zero numbers (`007`) | text |

In `--data`, JSON strings stay text unless they start with `=` (then formula). `--data` accepts strings, numbers, booleans, null; max 1,000,000 cells.

## --dry-run and --backup

Added to every action that modifies a file (including `create`, `convert`, `batch`):
- `--dry-run`: open, apply, report, do not save. Output gains `"dry_run": true`.
- `--backup`: before saving, copy the original to `<file>.bak-<UTC YYYYmmddTHHMMSSZ>` beside it. Output gains `"backup": "<path>"`. For `convert`, the copy is of an existing `dst`. Nothing is created for read-only actions or with `--dry-run`.

## Batch

```
batch FILE --ops '<JSON list>'      # or --ops-file PATH
```

Op: `{"action": "<name>", "<flag with _ for ->": value, ...}`. File is implied.
- Booleans: `true` adds the flag; `false`/`null` omit it. Lists and objects are passed as JSON text (`"data": [["a"]]`). `where` accepts a list.
- Not allowed as op action: `batch`, `create`, `convert`, `stop`, `status`. Not allowed as op keys: `file`, `dry_run`, `backup` (use the batch's own flags).
- **Atomic:** all ops run on one open document and it is saved once. Any failure (parse, validation, runtime) aborts with nothing saved. Read-only ops are allowed; a batch of only read-only ops saves nothing.
- Failure shape: `{"ok": false, "error": "op N (action): <msg>", "op": N, "action": "<name>"}`. **N is 0-based.**
- On `.csv`, an op of a [rich action](#csv-limits) fails before anything runs, as `op N (action): unsupported for csv`.
- Ops see each other's effects (e.g. `write` then `read`).

Example: `batch s.xlsx --ops '[{"action":"write","cell":"A1","value":"Hi"},{"action":"format","range":"A1","bold":true}]'`

## Units

| quantity | unit | notes |
|---|---|---|
| `col-width --width`, `get-format.col_width` | characters | 1 char = 2.3 mm (`width x 230` in 1/100 mm) |
| `row-height --height`, `get-format.row_height` | points | 1 pt = 0.3528 mm |
| `chart --width-mm/--height-mm`, `image --width-mm/--height-mm` | mm | chart defaults 160 x 90 |
| `get-format.borders.*.width_mm` | mm | `format --border` draws 0.26 mm solid lines |

`image` with one dimension keeps aspect ratio; with none, uses the image's natural size (96 dpi if it has no DPI).

## CSV limits

CSV has one sheet and no persistent formatting or objects. Handlers marked `rich` in code fail on `.csv` with `unsupported for csv`:

- Sheets: `add-sheet`, `delete-sheet`, `rename-sheet`, `copy-sheet`, `move-sheet`, `hide-sheet`, `show-sheet`, `protect`, `unprotect`
- Formatting/layout: `format`, `get-format`, `col-width`, `row-height`, `autofit`, `merge`, `unmerge`, `hide-rows`, `show-rows`, `hide-cols`, `show-cols`, `freeze`, `unfreeze`, `autofilter`, `cond-format`, `cond-format-clear`
- Objects: `chart`, `delete-chart`, `charts`, `image`, `comment`, `delete-comment`, `hyperlink`
- Other: `validation`, `validation-clear`, `define-name`, `delete-name`, `names`
- Also: `create` with more than one sheet.

Everything else works on csv: `info`, `read`, `write`, `write-range`, `append`, `clear`, `copy-range`, `move-range`, `fill`, `sort`, `dedupe`, `find`, `filter`, `stats`, `insert-rows/cols`, `delete-rows/cols`, `recalc`, `convert`, `batch` (of those), `status`, `stop`.

## Per-format behavior

CSV:
- Read/written as UTF-8, comma-separated, `"` quote.
- The sheet is always named `Sheet1` on load, whatever the file contained.
- Fields are number-detected on load: a text `007` written to csv reads back as `7`.
- Formulas are saved as their values; `read --formulas` then returns values.
- `convert` to csv writes only the first sheet (`skipped_sheets` lists the rest) and drops formatting.

xlsx:
- xlsx drops chart names on save. `charts`/`delete-chart` take the name from the chart's OLE shape name, which `chart --name` sets, so names survive.

xlsx vs ods:
- `charts` `range` for `scatter` may be reported differently per format (not guaranteed equal to the range you passed); other types report the source range.
- `--number-format` accepts any LibreOffice/Excel code (dates, currency, `0.00%`). Invalid code: `invalid number format: ...`.
- Freeze panes, charts, images, validation, comments, names, protection, conditional formats persist in both.

## Action semantics

- `find`: case-insensitive substring; `--exact` is whole-cell and case-sensitive. Booleans match as `true`/`false`.
- `filter`: `--where 'COLOP VALUE'` (ops `== != > < >= <= contains`; repeat to AND). If VALUE is numeric: compared numerically, against numeric cells; non-numeric cells never match `> < >= <=`, and for `==`/`!=` are compared as text. If not numeric: case-insensitive text compare of the cell's text (`<`/`>` are lexicographic). `contains` is case-insensitive substring. Empty cells compare as empty text. `--header` returns row 1 separately and excludes it from matching. Column beyond the used range fails.
- `sort`: `--header` leaves row 1; case-insensitive; sorts the used range.
- `dedupe`: removes later duplicates, keeping the first. Comparison is exact and case-sensitive on the values of `--cols` (default: all used columns). `--header` keeps row 1 and excludes it from comparison. Rows are physically deleted.
- `protect`/`unprotect`: act on `--sheet`, default first sheet only. `protect` fails if already protected, `unprotect` fails if not, or with `wrong password`.
- `chart --header`: first range row = series names and first range column = category labels. Without it all cells are data, no labels. `--name` must be unique across the workbook (`chart exists`); default `ChartN`. `bar` = horizontal bars, `column` = vertical.
- `format`: `--border-color` requires `--border` (default color `000000`). `--X` and `--no-X` together conflict. At least one option required. Colors: `RRGGBB`, `#RRGGBB` or 8-digit ARGB (alpha dropped). `--font-size` >= 1 integer. `--border none` clears borders.
- `cond-format`: needs `--fill`, `--font-color` or `--bold`. `between` needs `--value2`. `contains` is case-insensitive. `formula` takes the formula in `--value` relative to the range's top-left cell. Each call adds a rule; `cond-format-clear` removes all rules on the range.
- `validation`: `list` needs `--values a,b,c`; other types need `--min` and/or `--max` (`date` as `YYYY-MM-DD`).
- `define-name`: `--range` may be `Sheet2!A1:B3` or `'My Sheet'!A1`; otherwise `--sheet`. Duplicate name fails.
- `fill`: `down`/`right` copy the first row/col over the range (formulas adjust); `series` is linear from the first cell(s) with `--step`, first cells must be numeric. Range must span at least 2 rows (down) / columns (right).
- `freeze --cell C3`: freezes rows above 3 and columns left of C; `A1` fails (use `unfreeze`).
- `autofilter`: give exactly one of `--range` or `--off`; replaces existing autofilters on the sheet.
- `copy-sheet --position` / `move-sheet --position`: 1-based. Cannot delete the only sheet or hide the last visible sheet.
- `merge`: fails on a single cell or overlap with an existing merge; values outside the top-left cell are discarded.
- `convert`: fails if src and dst are the same file.
- `create`: fails if the file exists; `--sheets` comma-separated, no duplicates (case-insensitive).
- Ranges accept `$` and any corner order. Columns A-XFD, rows 1-1048576. Spans: `2:5`, `B:D`, single `3`/`B`. Sheet names: 1-31 chars, none of `[]:*?/\`.
- Saves are atomic (temp file, then replace). No `.~lock.*#` files are left behind.

## Limits and security

| limit | value | error |
|---|---|---|
| input file size | 50 MB | `file too large (max 50 MB)` |
| image file size | 50 MB | `image too large (max 50 MB)` |
| cells per `--data` / range | 1,000,000 | `... too large (max 1000000 cells)` |
| one call (soffice work) | 300 s | `operation timed out after 300s; daemon killed` |
| daemon startup | 30 s | `soffice did not accept connections within 30s` |
| waiting for another call's lock | 600 s | `another sheet call holds the daemon lock (timed out)` |

- Extensions other than `.xlsx`, `.ods`, `.csv`: `unsupported file type`. Missing file: `file not found: <path>`.
- Calls are serialized by a lock; concurrent callers queue. Env overrides: [development](development.md#environment-overrides).
- Missing LibreOffice: `soffice not found (install LibreOffice)`; missing `uno` module: `python uno module not available; run with system python3`.
- Documents open hidden and are always closed after the call.
