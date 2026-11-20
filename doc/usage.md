# Usage

Invocation and action list: [README](../README.md), [sheet skill](../.claude/skills/sheet/SKILL.md). Below: what the code actually outputs and enforces.

- [Output shapes](#output-shapes)
- [Auto-typing](#auto-typing)
- [CSV limits](#csv-limits)
- [ODS limitations](#ods-limitations)
- [Limits and security](#limits-and-security)

## Output shapes

Success: `{"ok": true, ...}`, exit 0. Failure: `{"ok": false, "error": "<msg>"}`, exit 1 (also for argparse errors and unexpected exceptions, as `"<ExceptionType>: <msg>"`). Output is UTF-8, `ensure_ascii=false`.

| action | fields after `ok` |
|---|---|
| info | `file`, `format`, `size` (bytes), `sheets`: `[{name, rows, cols}]` |
| read | `sheet`, `range` (null if sheet empty), then `data` (2D array, empty cells `null`) or, with `--as csv`, `csv` (string) |
| write | `sheet`, `cell` |
| write-range | `sheet`, `range` |
| append | `sheet`, `row` (first row written), `range` |
| create | `file`, `sheets` |
| add-sheet, delete-sheet, rename-sheet | `sheets` (names after change) |
| insert-rows, delete-rows | `sheet`, `at`, `count` |
| find | `sheet`, `count`, `matches`: `[{cell, value}]` |
| sort | `sheet`, `by` (uppercased), `desc` |
| convert | `src`, `dst`, `sheets`; plus `skipped_sheets` when dst is csv and src had more than one sheet |
| format | `sheet`, `range`, `applied` (sorted option names, e.g. `["bold","fill"]`) |
| col-width | `sheet`, `col` (uppercased), `width` |
| merge | `sheet`, `merged` |
| unmerge | `sheet`, `unmerged` (count of merges removed) |

Behavior notes:
- `read` without `--range` reads A1 through the last used row/column.
- `find`: default is case-insensitive substring; `--exact` is whole-cell and case-sensitive. Booleans match as `true`/`false`.
- `sort`: numbers, then booleans, then text (case-insensitive). Rows with an empty sort cell go last, even with `--desc`. `--header` leaves row 1.
- `create` fails if the file exists. `--sheets` is comma-separated.
- `convert` fails if src and dst are the same file. Formatting is copied only when dst supports it.
- `merge` fails on a single cell or overlap with an existing merge; non-top-left cell values in the range are discarded.
- `write`/`write-range`/`append`/etc. save atomically (temp file, then replace).
- Ranges accept `$` and any corner order (`C3:A1` = `A1:C3`). Columns A-XFD, rows 1-1048576.
- Sheet names: 1-31 chars, none of `[]:*?/\`.
- `--data`: JSON 2D array of strings/numbers/booleans/null; max 1,000,000 cells. `read`/`format` ranges are capped at the same size.
- `format` options: `--font-color`/`--fill` take 6-digit hex (leading `#` and 8-digit ARGB accepted; stored as 6-digit uppercase). `--font-size` >= 1. `col-width --width` > 0. `format` with no options fails.

## Auto-typing

Applies to `write --value` only. (`--data` keeps JSON types.) Checked in order:

| input | stored as |
|---|---|
| empty string | empty cell (cell cleared) |
| starts with `=` | formula (string) |
| `true`/`false` (any case) | boolean |
| integer matching `[+-]?(0\|[1-9]\d*)` | int |
| decimal/exponent number (`3.5`, `.5`, `1e3`) | float |
| anything else, including leading-zero numbers (`007`) | text |

Formulas are stored, not evaluated. Reading returns the formula text, not a computed value.

## CSV limits

- One sheet (named `Sheet1`), no styling.
- `format`, `col-width`, `merge`, `unmerge`, `add-sheet`, `delete-sheet`, `rename-sheet` fail with `unsupported for csv`.
- `create` on csv with more than one sheet fails with `unsupported for csv`.
- Read as UTF-8 (BOM accepted); each field is auto-typed with the rules above (so `007` stays text, `1.5` becomes float, `=...` becomes a formula string). Written as UTF-8, booleans as `true`/`false`, empty cells as empty fields.
- Invalid UTF-8 fails with `cannot read csv`.
- `convert` to csv writes only the first sheet and drops styling.

## ODS limitations

- Saving rewrites the whole file from the parsed model. Anything not modeled (charts, images, other styles, validation, etc.) is lost on any write action.
- Modeled: cell values, formulas, bold/italic/underline, font size/color, fill, horizontal align, number format, column widths, merges.
- Formulas are translated to/from `of:` syntax (`[.A1]`, `;`) by regex; complex formulas (sheet-qualified refs, etc.) may not round-trip.
- `--number-format` is limited to patterns like `General`, `0`, `0.00`, `#,##0`, `#,##0.00`, `0%`, `0.00%`; others fail with `number format not supported in ods`.
- Dates/times are read as ISO strings. Percent/currency cells are read as plain numbers.
- Column width uses 0.185 cm per character unit.
- Sheets over 1,000,000 populated cells fail with `ods sheet too large`.
- Files with no sheets fail with `ods file has no sheets`.

Similarly for xlsx: dates are read as ISO strings; openpyxl writes no cached formula results.

## Limits and security

| limit | value | error |
|---|---|---|
| input file size | 50 MB | `file too large (max 50 MB)` |
| uncompressed zip size (xlsx, ods) | 500 MB | `archive too large when uncompressed (max 500 MB)` |
| cells per `--data` / range | 1,000,000 | `... too large (max 1000000 cells)` |

- Extensions other than `.xlsx`, `.ods`, `.csv` fail with `unsupported file type`.
- ODS `content.xml` and `styles.xml` are parsed with `defusedxml` first, so entity-expansion and external-entity payloads are rejected before `odfpy` loads the file.
- Unreadable files fail with `cannot read xlsx|ods: <details>`.
