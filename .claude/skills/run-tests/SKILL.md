---
name: run-tests
description: "Run the sheet CLI skill accuracy suite (tests/run_tests.py) and interpret failures. Use when asked to run the tests, run the suite, measure skill accuracy, validate tests.csv, or check nondeterminism of the sheet skill. NOT for testing the sheet CLI code itself."
disable-model-invocation: true
allowed-tools: Bash(python3 tests/run_tests.py *), Read
---

# Rules

1. Run from the project root `/home/gargantua/code/claude-libre-calc`.
2. Run `--validate` first. Stop and fix `tests/tests.csv` if it fails.
3. Ask the user before any full run or any `--repeat` run that multiplies rows to the size of a full run. Each call is a `claude -p` request to the `--model` model (default `haiku`).
4. Do not edit `.claude/skills/sheet/SKILL.md` or `src/` to make a test pass unless the user asks.

# Commands

| Goal | Command |
|---|---|
| Check suite, no model calls | `python3 tests/run_tests.py --validate` |
| Smoke | `python3 tests/run_tests.py --ids 1,2,3` |
| One action | `python3 tests/run_tests.py --filter sort` |
| Nondeterminism | `python3 tests/run_tests.py --filter sort --repeat 5` |
| Full (confirm first) | `python3 tests/run_tests.py` |

Options: `--jobs N` (parallel, default 4), `--timeout S` (default 120), `--model ALIAS_OR_ID` (default `haiku`; e.g. `sonnet`), `--backend cli` (`api` is not implemented).

# Output

- Summary prints to stdout: model, overall, per action, then each failure.
- Per-row CSV: `tests/results/<UTC timestamp>.csv`. Columns: id, rep, model, action, pass, action_match, args_match, prompt, expected, raw, diff, error.
- Exit code 0 only if every row passed.

# Reading failures

- `action_match` false: model chose the wrong action. Fix the action's table row or description in the sheet skill.
- `action_match` true, `args_match` false: read `diff` (JSON of mismatched keys, expected vs got). Fix the skill text for that option.
- `error` = `argparse error` or `no known action`: model output was not a valid command. Read `raw`.
- Any other `error`: `claude` call failed (timeout, auth). Not a skill defect; rerun that id.
- With `--repeat`, a row passing under 100% is nondeterministic: tighten the skill wording, not the test.
- If `diff` shows a prompt ambiguity (two valid commands), fix the prompt and `expected` in `tests/tests.csv`, then `--validate`.

# Example

User: "Run the sheet tests."

1. `python3 tests/run_tests.py --validate` -> `validate: <N> rows, 0 problems`.
2. Ask: "Full run makes <N> calls to <model>. Proceed?"
3. After yes: `python3 tests/run_tests.py`, then report the overall and per-action accuracy and the failing ids with their `diff`.
