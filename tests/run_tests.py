#!/usr/bin/env python3
"""Accuracy harness for .claude/skills/sheet/SKILL.md.

Each row of tests/tests.csv is sent to a fresh model whose only system prompt is
the skill file; its one-line command is parsed with sheetcli.cli.build_parser()
and compared with the parsed `expected` command.

Isolation (verified by probe, claude CLI with OAuth, cwd = empty temp dir):
  - Without extra flags, user ~/.claude/CLAUDE.md LEAKS into the model context.
  - `--setting-sources project` removes it (also verified:
    CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 works). Both are applied here.
  - Still visible and not suppressible: a userEmail context block, basic
    environment info (cwd, platform), and organization-managed instructions.
  - `--bare` is unusable (needs an API key); the `api` backend is the fully
    clean alternative (not implemented).

Usage:
  run_tests.py --validate
  run_tests.py [--filter ACTION] [--ids 1,2] [--jobs 4] [--repeat N] [--timeout S]
               [--model ALIAS_OR_ID]   (default haiku; passed to `claude -p --model`)
"""
import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude/skills/sheet/SKILL.md"
TESTS = ROOT / "tests/tests.csv"
RESULTS = ROOT / "tests/results"
SUFFIX = (
    "Respond with exactly one shell command line and nothing else. "
    "No code fences, no explanation."
)
REF_KEYS = {"cell", "range", "start", "col", "by"}

sys.path.insert(0, str(ROOT / "src"))
from sheetcli.cli import build_parser  # noqa: E402


def action_names(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return set(a.choices)
    raise RuntimeError("build_parser() has no subcommands")


def extract_command(text):
    for line in text.strip().splitlines():
        line = line.strip().strip("`").strip()
        if line and not line.startswith("```"):
            return line
    return ""


def parse_command(line, parser, actions):
    """Return (action, normalized args dict, error)."""
    try:
        tokens = shlex.split(line)
    except ValueError as e:
        return None, None, f"shlex: {e}"
    idx = next((i for i, t in enumerate(tokens) if t in actions), None)
    if idx is None:
        return None, None, "no known action"
    tokens = tokens[idx:]
    try:
        ns = parser.parse_args(tokens)
    except SystemExit:
        return tokens[0], None, "argparse error"
    return tokens[0], normalize(vars(ns)), None


def normalize(d):
    out = {}
    for k, v in d.items():
        if callable(v):
            continue
        if k == "data" and isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        elif k in REF_KEYS and isinstance(v, str):
            v = v.upper()
        out[k] = v
    return out


def diff(exp, got):
    return {
        k: {"expected": exp.get(k), "got": got.get(k)}
        for k in sorted(set(exp) | set(got))
        if exp.get(k) != got.get(k)
    }


def call_cli(prompt, timeout, model):
    env = {**os.environ, "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1"}
    cmd = [
        "claude", "-p", "--model", model, "--tools", "",
        "--system-prompt-file", str(SKILL),
        "--append-system-prompt", SUFFIX,
        "--disable-slash-commands", "--strict-mcp-config",
        "--no-session-persistence", "--setting-sources", "project",
        "--output-format", "json",
    ]
    with tempfile.TemporaryDirectory() as cwd:
        r = subprocess.run(
            cmd, input=prompt, cwd=cwd, env=env,
            capture_output=True, text=True, timeout=timeout,
        )
    if r.returncode != 0:
        raise RuntimeError(f"claude exit {r.returncode}: {r.stderr.strip()[:300]}")
    data = json.loads(r.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude error: {data.get('result')}")
    return data["result"]


API_MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}


def call_api(prompt, timeout, model):
    """Not implemented. Plan: ANTHROPIC_API_KEY from env; map alias via
    API_MODELS (haiku -> claude-haiku-5-5, sonnet -> claude-sonnet-5-5; full ids
    pass through); max_tokens 256; temperature 0; skill file as system prompt."""
    raise NotImplementedError("api backend: ANTHROPIC_API_KEY, temperature 0")


BACKENDS = {"cli": call_cli, "api": call_api}


def run_one(row, rep, backend, timeout, model, parser, actions):
    exp_action, exp_args, _ = parse_command(row["expected"], parser, actions)
    res = {
        "id": row["id"], "rep": rep, "model": model, "action": row["action"], "prompt": row["prompt"],
        "expected": row["expected"], "raw": "", "action_match": False,
        "args_match": False, "pass": False, "diff": "", "error": "",
    }
    try:
        raw = backend(row["prompt"], timeout, model)
    except NotImplementedError:
        raise
    except Exception as e:
        res["error"] = str(e)
        return res
    res["raw"] = raw
    act, args, err = parse_command(extract_command(raw), parser, actions)
    res["action_match"] = act == exp_action
    if err:
        res["error"] = err
        return res
    d = diff(exp_args, args)
    res["args_match"] = not d
    res["pass"] = res["action_match"] and res["args_match"]
    res["diff"] = json.dumps(d) if d else ""
    return res


def load_rows():
    with open(TESTS, newline="") as f:
        return list(csv.DictReader(f))


def validate(rows, parser, actions):
    bad = 0
    for row in rows:
        act, args, err = parse_command(row["expected"], parser, actions)
        if err or act != row["action"]:
            bad += 1
            print(f"FAIL id={row['id']} {row['action']}: {err or 'action mismatch: ' + str(act)} :: {row['expected']}")
    counts = defaultdict(int)
    for r in rows:
        counts[r["action"]] += 1
    for a in sorted(actions):
        if counts[a] != 5:
            bad += 1
            print(f"FAIL action {a} has {counts[a]} rows (want 5)")
    print(f"validate: {len(rows)} rows, {bad} problems")
    return bad == 0


def summarize(results, repeat, model):
    by_action = defaultdict(list)
    by_row = defaultdict(list)
    for r in results:
        by_action[r["action"]].append(r["pass"])
        by_row[r["id"]].append(r["pass"])
    total = sum(r["pass"] for r in results)
    print(f"\nmodel: {model}")
    print(f"overall: {total}/{len(results)} = {total / len(results):.1%}")
    print("per action:")
    for a, v in sorted(by_action.items()):
        print(f"  {a:14s} {sum(v)}/{len(v)}  {sum(v) / len(v):.0%}")
    if repeat > 1:
        print("per row pass rate (non-100% only):")
        for i, v in sorted(by_row.items(), key=lambda kv: int(kv[0])):
            if sum(v) != len(v):
                print(f"  id {i}: {sum(v)}/{len(v)}")
    for r in results:
        if not r["pass"]:
            print(f"\nFAIL id={r['id']} rep={r['rep']} {r['action']}\n  prompt:   {r['prompt']}\n"
                  f"  expected: {r['expected']}\n  got:      {extract_command(r['raw'])}\n"
                  f"  action_match={r['action_match']} args_match={r['args_match']}"
                  f" error={r['error']!r}\n  diff: {r['diff']}")


def write_results(results):
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    cols = ["id", "rep", "model", "action", "pass", "action_match", "args_match",
            "prompt", "expected", "raw", "diff", "error"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(results)
    print(f"results: {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--filter", metavar="ACTION")
    ap.add_argument("--ids", help="comma-separated row ids")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--model", default="haiku",
                    help="model alias or id passed to claude -p --model (default: haiku)")
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="cli")
    a = ap.parse_args()

    parser = build_parser()
    actions = action_names(parser)
    rows = load_rows()
    if a.validate:
        sys.exit(0 if validate(rows, parser, actions) else 1)
    if a.filter:
        rows = [r for r in rows if r["action"] == a.filter]
    if a.ids:
        want = set(a.ids.split(","))
        rows = [r for r in rows if r["id"] in want]
    if not rows:
        sys.exit("no rows selected")

    backend = BACKENDS[a.backend]
    jobs = [(r, i) for r in rows for i in range(1, a.repeat + 1)]
    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        results = list(ex.map(
            lambda j: run_one(j[0], j[1], backend, a.timeout, a.model, parser, actions), jobs))
    summarize(results, a.repeat, a.model)
    write_results(results)
    sys.exit(0 if all(r["pass"] for r in results) else 1)


if __name__ == "__main__":
    main()
