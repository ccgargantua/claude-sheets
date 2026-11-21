# Testing

Two suites:
- Unit tests (`tests/unit`): test CLI code. See [Unit tests](#unit-tests).
- Agent suite (`tests/run_tests.py`): tests the sheet skill. Rest of this page.

- [Unit tests](#unit-tests)
- [Design](#design)
- [tests.csv](#testscsv)
- [Running](#running)
- [Isolation](#isolation)
- [Comparison](#comparison)
- [Nondeterminism](#nondeterminism)
- [Results](#results)
- [API backend plan](#api-backend-plan)

## Unit tests

```
python3 -m unittest discover -s tests/unit      # ~3 min
```

Needs LibreOffice (`soffice`) and `python3-uno`; tests drive the real backend. Each module sets `SHEETCLI_STATE_DIR` to a temp dir in `setUpModule` (own daemon, pipe, profile; stopped in `tearDownModule`), so tests never touch the repo's `.sheetcli/`.

| file | covers |
|---|---|
| `test_sheet.py` | parser (61 actions, `--dry-run`/`--backup` only on mutating handlers, import without `uno`), create/info/read/write/append, typing, formulas, dates, sort/find, sheets, format/col-width/merge, convert, batch, dry-run/backup, limits, daemon (start/reuse/stop, recovery, idle watchdog, parallel serialization). Defines shared `Base`, `FORMATS`, `RICH`, `sheet()` |
| `test_structure_formatting.py` | copy/move/hide sheets, hide/show rows/cols, freeze, insert/delete cols, clear, copy/move/fill, row-height/autofit/get-format, cond-format, autofilter, csv gating |
| `test_data_query_charts.py` | names, validation, comments, hyperlinks, protect, filter/dedupe/stats, charts, images, csv gating |

Conventions: multi-format tests loop over `xlsx`/`ods` (`RICH`) or all of `FORMATS` with `subTest`; files are re-inspected after saving; every test checks no stray `.~lock*` or `.sheetcli-*.tmp` files are left.

## Design

Each row's `prompt` goes to a fresh model whose system prompt is `.claude/skills/sheet/SKILL.md` plus an instruction to answer with one shell command line. The command is parsed with `build_parser()` (the real 61-action parser; `sheet` in the command stands for `python3 src/sheet.py`) and compared to the parsed `expected`. Nothing is executed.

## tests.csv

| column | meaning |
|---|---|
| `id` | Integer row id (used by `--ids`) |
| `action` | Action under test (used by `--filter`) |
| `prompt` | User request given to the model |
| `expected` | Correct command, e.g. `sheet info report.xlsx` |

`tests.csv` has 305 rows: 61 actions x 5. `--validate` checks that every `expected` parses, its action equals `action`, and each action has exactly 5 rows. It needs no `soffice` or `uno` (parsing only).

## Running

```
python3 tests/run_tests.py --validate            # no model calls; run first
python3 tests/run_tests.py --ids 1,2,3           # smoke
python3 tests/run_tests.py --filter sort         # one action (any of the 61)
python3 tests/run_tests.py --filter sort --repeat 5
python3 tests/run_tests.py                       # full: one call per row
```

Options: `--jobs N` (default 4), `--timeout S` (default 120), `--model ALIAS_OR_ID` (default `haiku`; e.g. `sonnet`), `--backend cli|api` (default `cli`; `api` raises not implemented). Exit 0 only if every row passed.

Each call is a `claude -p` request to the `--model` model. Estimate cost before full or large `--repeat` runs.

Harness command (`cli` backend), run in an empty temp dir:

```
claude -p --model <model> --tools "" \
  --system-prompt-file .claude/skills/sheet/SKILL.md \
  --append-system-prompt "<one-command suffix>" \
  --disable-slash-commands --strict-mcp-config --no-session-persistence \
  --setting-sources project --output-format json
```

with env `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` and the prompt on stdin.

## Isolation

| measure | effect |
|---|---|
| `--tools ""` | no tools |
| `--system-prompt-file` | skill replaces the default system prompt |
| `--setting-sources project` + `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` | user `~/.claude/CLAUDE.md` no longer leaks (verified by probe) |
| empty temp cwd | no project files/CLAUDE.md |
| `--disable-slash-commands`, `--strict-mcp-config`, `--no-session-persistence` | no skills, MCP servers, or session state |

Still leaks (cannot be suppressed with the CLI backend):
- `userEmail` context block
- basic environment info (cwd, platform)
- organization-managed instructions

`--bare` would remove these but requires an API key. Only the future [api backend](#api-backend-plan) isolates fully.

## Comparison

Both commands are parsed with the real argparse parser, then normalized, so option order and quoting do not matter:
- The first token that is a known action starts the command (a leading `python src/sheet.py` is ignored); only the first non-empty line of the reply is used, backticks stripped.
- `--data` and `--ops` are compared as parsed JSON. For `--ops`, each op object is normalized the same way (op `data` parsed; op `cell`, `range`, `start`, `col`, `by` uppercased), so key order and quoting inside ops do not matter. `--ops-file` is compared as a path string.
- `cell`, `range`, `start`, `col`, `by` are uppercased.
- Pass = same action and identical args.

Row errors (empty `pass`): `no known action`, `argparse error` (invalid command), or a `claude` failure (timeout, auth; not a skill defect, rerun).

## Nondeterminism

`--repeat N` runs each selected row N times (column `rep`). The summary lists rows with less than 100% pass rate; fix the skill wording for those, not the test. Prompts that allow two valid commands should be fixed in `tests.csv` and re-validated.

## Results

- Summary on stdout: model, overall, per action, per-row rates (with `--repeat`), then each failure.
- Per-row CSV: `tests/results/<UTC timestamp>.csv` with columns `id, rep, model, action, pass, action_match, args_match, prompt, expected, raw, diff, error`. `diff` is JSON `{key: {expected, got}}`.

## API backend plan

`call_api` in `tests/run_tests.py` is a stub (`BACKENDS["api"]`). Plan:
- Read `ANTHROPIC_API_KEY` from env.
- Send the skill file as the system prompt plus the one-command suffix as the user/system instruction, no tools, `temperature 0`.
- Model: `--model` alias mapped to `haiku` -> `claude-haiku-5-5`, `sonnet` -> `claude-sonnet-5-5` (full ids pass through); `max_tokens 256`.
- Return the response text; everything downstream is unchanged.
- Gives full isolation (no CLAUDE.md, email, env info, or managed instructions) and reproducibility.
