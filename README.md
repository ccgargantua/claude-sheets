# claude-libre-calc

Python CLI that lets agents read, write, and format `.xlsx`, `.csv`, and `.ods` files through a LibreOffice (UNO) backend. 61 actions. Every command prints one JSON object.

## Setup

Install LibreOffice and its Python bridge (`python3-uno`, e.g. `apt install libreoffice-calc python3-uno`). Use the system `python3`: no venv, no `requirements.txt`, no pip packages.

## Usage

```
python3 src/sheet.py <action> <file> [options]
```

Full action table: [`.claude/skills/sheet/SKILL.md`](.claude/skills/sheet/SKILL.md). Output shapes, typing rules, limits: [doc/usage.md](doc/usage.md).

**Daemon:** the first call auto-starts a headless `soffice` (state and profile in `.sheetcli/`, gitignored); later calls reuse it. It exits after 10 idle minutes. `python3 src/sheet.py status` shows it, `python3 src/sheet.py stop` stops it. Details: [doc/development.md](doc/development.md#daemon).

## Tests

Unit tests (CLI code; needs `soffice`, ~3 min):

```
python3 -m unittest discover -s tests/unit
```

Agent suite (measures how accurately a model turns prompts into commands using the sheet skill):

```
python3 tests/run_tests.py --validate        # no model calls
python3 tests/run_tests.py --filter sort     # filtered run
python3 tests/run_tests.py --model sonnet    # choose model (default haiku)
```

Details: [doc/testing.md](doc/testing.md). Extending the CLI: [doc/development.md](doc/development.md).

## Layout

```
src/sheet.py                entry point
src/sheetcli/               CLI package
  cli.py                    parser + main
  session.py                run_ops: open doc, apply ops, save once
  document.py, cells.py     UNO document and cell helpers
  uno_daemon.py             soffice daemon lifecycle
  watchdog.py               idle-timeout killer
  common.py                 limits, parsing, autotype
  actions/                  one module per action group, Handler registry
tests/unit/                 unit tests (real soffice)
tests/run_tests.py          agent-suite harness
tests/tests.csv             agent-suite prompts + expected commands (305 rows)
tests/results/              per-run CSVs
.sheetcli/                  daemon state (gitignored)
.claude/skills/sheet/       skill given to agents
.claude/skills/run-tests/   skill for running the agent suite
doc/                        usage, development, testing docs
```

## Agent Suite Results

### v2 (UNO backend, 61 actions)

2026-11-20, 305 prompts (5/action), 1 rep, `cli` backend.

| model | overall | misses |
|---|---|---|
| haiku | 296/305 (97.0%) | 9 actions at 4/5, one miss each. Shell commands instead of the CLI: read (`cat`), create (`touch`). Asked a question instead of answering: rename-sheet, unfreeze. Wrong flag or action: delete-cols (invented `--cols C:E`), show-rows (used `read`), delete-comment (used `comment --text ''`). Malformed command: row-height (put `--sheet` before the action), comment (left a literal `FILE` placeholder). |

After this run, rules 7-10 were added to the sheet skill to target these misses (no shell commands, no questions or prose, no placeholders, action right after `sheet`). Not yet rerun.

### v1 (openpyxl/odfpy backend, 18 actions)

2026-11-20, 90 prompts, 1 rep each, `cli` backend.

| model | overall | misses |
|---|---|---|
| sonnet | 90/90 (100%) | none |
| haiku | 86/90 (95.6%) | col-width 3/5 (invented `format --col-width` and `format-width`), sort 4/5 (added unrequested `--header`), write-range 4/5 (inserted an empty row in `--data`) |

Raw per-row CSVs: `tests/results/` (gitignored). Single runs; nondeterminism not yet measured (`--repeat`).
