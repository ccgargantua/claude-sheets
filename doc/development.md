# Development

- [Architecture](#architecture)
- [Add an action](#add-an-action)

## Architecture

Package `src/sheetcli/`, entry `src/sheet.py` (adds `src/` to `sys.path`, calls `cli.main`).

| module | role |
|---|---|
| `cli.py` | `build_parser()` (argparse; errors print JSON, exit 1), `run()`, `main()` (wraps result in `ok`, catches errors) |
| `actions.py` | One function per action, taking the parsed args and returning a dict; `ACTIONS` maps name to function |
| `store.py` | Extension to format, `open_book`/`new_book`/`save_book` (atomic temp + replace) |
| `xlsx.py` | `XlsxBook`/`XlsxSheet` over openpyxl |
| `ods.py` | `OdsBook` (read via odfpy, write via `_Writer`), formula and number-format translation |
| `csvio.py` | `CsvBook` (single sheet, no formatting) |
| `model.py` | `Book` base (sheet management, capability flags `formatting`, `multi_sheet`) and `MemSheet` (in-memory cells/styles/merges/widths) |
| `common.py` | Limits, `SheetError`, cell/range parsing, `autotype`, validation helpers |

Sheet interface used by actions: `name`, `max_row`, `max_col`, `get`, `set`, `items`, `insert_rows`, `delete_rows`, `merges`, `merge`, `unmerge`, `apply_format`, `style_items`, `set_col_width`, `width_items`.

Raise `SheetError` for user errors; any other exception is reported as `Type: msg`.

Lazy imports: `store.py` imports `xlsx`/`ods`/`csvio` inside the functions that need them, so importing `sheetcli.cli` and calling `build_parser()` needs no third-party packages. The test harness relies on this (it runs with system `python3`).

## Add an action

1. **Parser** (`cli.py`, `build_parser`): `cmd("name", ...)` adds a subparser with positional `file` by default; add options. Use `sheet_opt(...)` for `--sheet`.
2. **Handler** (`actions.py`): `def name_(a): ...` returns a dict (no `ok`); add it to `ACTIONS`. Mutating actions load, change, then `save_book`. Gate formatting-only actions with `book.require_formatting()`.
3. **Skill table** (`.claude/skills/sheet/SKILL.md`): add a row to the action table (and notes if the action needs new notation).
4. **Agent tests** (`tests/tests.csv`): add 5 rows (`id,action,prompt,expected`), unique ids. `--validate` requires exactly 5 per action and each `expected` to parse. See [testing](testing.md).
5. **Unit test** (`tests/unit/test_sheet.py`): cover the action across `xlsx`, `ods`, `csv` (`FORMATS`) or assert `unsupported for csv`.
6. Document the output shape in [usage.md](usage.md).

Verify: `.venv/bin/python -m unittest discover -s tests/unit` and `python3 tests/run_tests.py --validate`.
