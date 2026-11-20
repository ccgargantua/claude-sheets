# Testing

Two suites:
- Unit tests (`tests/unit`): test CLI code. `.venv/bin/python -m unittest discover -s tests/unit`.
- Agent suite (`tests/run_tests.py`): tests the sheet skill. Rest of this page.

- [Design](#design)
- [tests.csv](#testscsv)
- [Running](#running)
- [Isolation](#isolation)
- [Comparison](#comparison)
- [Nondeterminism](#nondeterminism)
- [Results](#results)
- [API backend plan](#api-backend-plan)

## Design

Each row's `prompt` goes to a fresh model whose system prompt is `.claude/skills/sheet/SKILL.md` plus an instruction to answer with one shell command line. The command is parsed with `build_parser()` and compared to the parsed `expected`. Nothing is executed.

## tests.csv

| column | meaning |
|---|---|
| `id` | Integer row id (used by `--ids`) |
| `action` | Action under test (used by `--filter`) |
| `prompt` | User request given to the model |
| `expected` | Correct command, e.g. `sheet info report.xlsx` |

`--validate` checks that every `expected` parses, its action equals `action`, and each action has exactly 5 rows.

## Running

```
python3 tests/run_tests.py --validate            # no model calls; run first
python3 tests/run_tests.py --ids 1,2,3           # smoke
python3 tests/run_tests.py --filter sort         # one action
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
- `--data` is compared as parsed JSON.
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
