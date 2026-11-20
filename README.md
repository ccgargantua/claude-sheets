# claude-libre-calc

Python CLI that lets agents read, write, and format `.xlsx`, `.csv`, and `.ods` files. Every command prints one JSON object.

## Setup

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Usage

```
.venv/bin/python src/sheet.py <action> <file> [options]
```

Full action table: [`.claude/skills/sheet/SKILL.md`](.claude/skills/sheet/SKILL.md). Output shapes, typing rules, limits: [doc/usage.md](doc/usage.md).

## Tests

Unit tests (CLI code):

```
.venv/bin/python -m unittest discover -s tests/unit
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
src/sheet.py              entry point
src/sheetcli/             CLI package
tests/unit/               unit tests
tests/run_tests.py        agent-suite harness
tests/tests.csv           agent-suite prompts + expected commands
tests/results/            per-run CSVs
.claude/skills/sheet/     skill given to agents
.claude/skills/run-tests/ skill for running the agent suite
doc/                      usage, development, testing docs
```

## Agent Suite Results

2026-11-20, 90 prompts, 1 rep each, `cli` backend.

| model | overall | misses |
|---|---|---|
| sonnet | 90/90 (100%) | none |
| haiku | 86/90 (95.6%) | col-width 3/5 (invented `format --col-width` and `format-width`), sort 4/5 (added unrequested `--header`), write-range 4/5 (inserted an empty row in `--data`) |

Raw per-row CSVs: `tests/results/` (gitignored). Single runs; nondeterminism not yet measured (`--repeat`).
