# Development

- [Architecture](#architecture)
- [Handler registry](#handler-registry)
- [Request flow](#request-flow)
- [Daemon](#daemon)
- [Environment overrides](#environment-overrides)
- [Add an action](#add-an-action)

## Architecture

Package `src/sheetcli/`, entry `src/sheet.py` (adds `src/` to `sys.path`, calls `cli.main`). Backend: LibreOffice UNO only (system `python3` + `python3-uno`; stdlib otherwise).

| module | role |
|---|---|
| `cli.py` | `build_parser()` (argparse; errors print JSON, exit 1; `raise_errors=True` raises `SheetError` instead, used by batch), `run()`, `main()` (wraps result in `ok`, catches errors, adds `SheetError.extra` fields) |
| `actions/__init__.py` | `MODULES` tuple and merged `HANDLERS` dict; duplicate names raise at import |
| `actions/base.py` | `Handler`, `cmd()` (subparser with positional `file`), `with_sheet()` (adds `--sheet`) |
| `actions/core.py` | info, read, write, write-range, append, create, convert, batch, recalc, status, stop |
| `actions/structure.py` | sheets, rows/cols, clear, copy/move, fill, hide/show, freeze, autofilter |
| `actions/formatting.py` | format, col-width, merge/unmerge, row-height, autofit, get-format, cond-format(-clear) |
| `actions/data.py` | names, validation, comment, hyperlink, protect/unprotect |
| `actions/query.py` | find, sort, filter, dedupe, stats |
| `actions/charts.py` | chart, delete-chart, charts, image |
| `session.py` | `execute()` and `run_ops()`: open doc, run handlers, save once |
| `document.py` | `Doc` wrapper (sheet lookup, number formats, formula parse/print, recalc, save), `open_doc`/`new_doc` context managers, atomic `store`, `backup_file`, lock-file cleanup |
| `cells.py` | `read_grid`/`write_grid`, `used_range`, range/row-span/col-span helpers |
| `common.py` | limits, `SheetError`, A1/range/span parsing, `autotype`, color/sheet-name validation |
| `uno_daemon.py` | `connection()` context manager, `status()`, `stop()` |
| `watchdog.py` | detached idle killer; also process helpers (`process_alive`, `kill_group`, `idle_for`) |

`uno` is imported lazily inside functions, so importing `sheetcli.cli` and calling `build_parser()` needs no `uno`. The test harness relies on this.

Raise `SheetError(msg)` for user errors; other exceptions are reported as `Type: msg`.

## Handler registry

Each action module has `register(sub)` (adds subparsers) and `HANDLERS = {"name": Handler(...)}`.

`Handler(fn, mutates=False, rich=False, free=False)`:

| field | meaning |
|---|---|
| `fn` | `fn(doc, args) -> dict` (or `fn(args)` when `free`). `None` = reported as `not implemented: <action>` |
| `mutates` | saves the doc; `build_parser` adds `--dry-run` and `--backup` to the action |
| `rich` | unsupported on `.csv` (error `unsupported for csv`, raised before the doc opens; also in batch) |
| `free` | opens its own session (`create`, `convert`, `batch`, `status`, `stop`); not run through `run_ops` |

`build_parser` raises if the registered parsers and `HANDLERS` keys differ.

## Request flow

1. `cli.run` parses args, `session.execute` picks the handler.
2. Non-free: `run_ops(path, [(args, handler)])` checks the file (exists, <= 50 MB), rejects `rich` on csv, opens the doc hidden via the daemon `connection()`, runs `fn(doc, args)`, then saves once if any op mutates (unless `--dry-run`; `--backup` copies first).
3. `batch` parses every op through the real parser (so flags are validated identically), then calls `run_ops(..., indexed=True)`; errors become `op N (action): msg` with `op` (0-based) and `action` fields. Any failure raises before `doc.save()`, so nothing is written.
4. Doc is closed in `finally`; `.~lock.<file>#` removed. Saves write a temp file beside the target, then `os.replace`.

## Daemon

- First call starts `soffice --headless --invisible --nologo --norestore --nodefault --accept=pipe,name=sheetcli-<uid>;urp;` with profile `<repo>/.sheetcli/profile`. Later calls connect over the pipe.
- State in `.sheetcli/` (gitignored): `profile/`, `pid`, `last_used` (mtime = last activity), `lock`.
- `lock` is an `flock`: calls are serialized across processes.
- `watchdog.py` is spawned detached at startup; it kills the soffice process group when `last_used` is older than the idle timeout (default 600 s) and no call holds the lock.
- A per-call timer kills the daemon if a call exceeds the call timeout, so a call cannot hang.
- A dead or stale daemon (killed process, stale pid, profile lock) is cleared and restarted on the next call.
- `status` and `stop` are CLI actions.

## Environment overrides

| variable | default | effect |
|---|---|---|
| `SHEETCLI_STATE_DIR` | `<repo>/.sheetcli` | State/profile dir; also changes the pipe name, so it gets its own daemon. Unit tests use a temp dir per module |
| `SHEETCLI_IDLE_SECONDS` | 600 | Idle time before the watchdog kills the daemon |
| `SHEETCLI_CONNECT_TIMEOUT` | 30 | Seconds to wait for soffice to accept connections |
| `SHEETCLI_CALL_TIMEOUT` | 300 | Max seconds for one call before the daemon is killed |
| `SHEETCLI_LOCK_TIMEOUT` | 600 | Max seconds to wait for the call lock |

## Add an action

1. **Parser + handler** in the matching `actions/<module>.py`: add the subparser in `register` (`cmd(sub, "name")`, `with_sheet(...)`, options), write `def name(doc, a): ...` returning a dict (no `ok`), and add `"name": Handler(name, mutates=..., rich=...)` to `HANDLERS`. Set `rich=True` if it cannot work on csv. Use `doc.sheet(a.sheet)` to resolve the sheet.
2. **Skill table** (`.claude/skills/sheet/SKILL.md`): add a row (and disambiguation or notation notes if needed).
3. **Agent tests** (`tests/tests.csv`): add 5 rows (`id,action,prompt,expected`), unique ids. `--validate` requires exactly 5 per action and each `expected` to parse. See [testing](testing.md).
4. **Unit test** (`tests/unit/`): cover the action on `xlsx` and `ods` (`RICH`) or all of `FORMATS`, or assert `unsupported for csv`. Update the action count in `ParserTests.test_61_actions_and_flags`.
5. Document the output shape and limits in [usage.md](usage.md).

Verify: `python3 -m unittest discover -s tests/unit` and `python3 tests/run_tests.py --validate`.
