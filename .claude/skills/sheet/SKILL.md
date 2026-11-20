---
name: sheet
description: "Read and edit spreadsheet files (.xlsx, .csv, .ods) through the sheet CLI. Use when asked to read, write, append, sort, search, format, merge, convert, or manage sheets in a spreadsheet file."
---

# Rules

1. `sheet` means `python src/sheet.py`. Invoke as `sheet <action> <file> [options]`.
2. Output one command per request. Use only actions and options in the table below.
3. Pass only options the user's request implies. Omit options that are at their default.
4. Wrap JSON and any value with spaces, `=`, `$`, `#` or `!` in single quotes. Use double quotes inside the JSON.
5. Option values go after the flag: `--sheet Sales`, never `--sheet=Sales`.

# Actions

| action | args | description |
|---|---|---|
| info | FILE | List sheets and their dimensions |
| read | FILE [--sheet S] [--range A1:C10] [--as json\|csv] | Read cells. Default: first sheet, whole sheet, `json` |
| write | FILE --cell A1 --value V [--sheet S] | Set one cell. V starting with `=` is a formula |
| write-range | FILE --start A1 --data JSON [--sheet S] | Write a 2D array with its top-left at `--start` |
| append | FILE --data JSON [--sheet S] | Add rows after the last used row |
| create | FILE [--sheets S1,S2] | Create a new file. Default sheet list: `Sheet1` |
| add-sheet | FILE --name N | Add a sheet |
| delete-sheet | FILE --name N | Delete a sheet |
| rename-sheet | FILE --name OLD --new-name NEW | Rename a sheet |
| insert-rows | FILE --at N [--count K] [--sheet S] | Insert K blank rows (default 1) before row N |
| delete-rows | FILE --at N [--count K] [--sheet S] | Delete K rows (default 1) starting at row N |
| find | FILE --query Q [--exact] [--sheet S] | Find cells containing Q. `--exact` = whole-cell match |
| sort | FILE --by COL [--desc] [--header] [--sheet S] | Sort rows by column letter. Default ascending. `--header` keeps row 1 in place |
| convert | SRC DST | Convert between formats by file extension |
| format | FILE --range R [--bold] [--italic] [--underline] [--font-size N] [--font-color HEX] [--fill HEX] [--number-format F] [--align left\|center\|right] [--sheet S] | Style cells in a range |
| col-width | FILE --col COL --width W [--sheet S] | Set column width (number) |
| merge | FILE --range R [--sheet S] | Merge cells in a range |
| unmerge | FILE --range R [--sheet S] | Unmerge cells in a range |

# Notation

- Cells: A1 style (`B7`). Ranges: `A1:C10`. Columns: letters (`C`). Rows: 1-based integers.
- `--sheet` omitted = first sheet.
- Types are auto-detected: `42` int, `3.5` float, `true`/`false` bool, else text.
- Formula: `--value '=SUM(A1:A10)'`.
- Colors: hex such as `FF0000`. Pass exactly as the user gave it.

# Data format

`--data` is a JSON 2D array: a list of rows, each a list of cell values. Strings in double quotes, numbers and booleans bare, formulas as strings starting with `=`.

```
--data '[["Name","Qty"],["apple",3],["pear",5.5],["total","=SUM(B2:B3)"]]'
```

A single row is still 2D: `'[["a","b","c"]]'`.

# Output

Every command prints one JSON object. Success: `{"ok": true, ...}`. Failure: `{"ok": false, "error": "..."}` with exit code 1.

# CSV limits

- `.csv` holds one sheet and no styling.
- On `.csv`: `format`, `col-width`, `merge`, `unmerge`, `add-sheet`, `delete-sheet`, `rename-sheet` fail with `"unsupported for csv"`.

# Example

User: "In budget.xlsx, put the formula summing B2 to B9 into B10 on the Q1 sheet."

`sheet write budget.xlsx --cell B10 --value '=SUM(B2:B9)' --sheet Q1`
