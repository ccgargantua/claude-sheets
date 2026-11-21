import argparse
import json
import sys

from .actions import HANDLERS, MODULES
from .common import SheetError


class _ExitingParser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"ok": False, "error": message}))
        sys.exit(1)


class _RaisingParser(argparse.ArgumentParser):
    def error(self, message):
        raise SheetError(message)


def build_parser(raise_errors=False):
    cls = _RaisingParser if raise_errors else _ExitingParser
    p = cls(prog="sheet", description="Spreadsheet CLI (.xlsx, .ods, .csv) on LibreOffice UNO; JSON output")
    sub = p.add_subparsers(dest="action", required=True, parser_class=cls)
    for module in MODULES:
        module.register(sub)
    if sub.choices.keys() != HANDLERS.keys():
        raise RuntimeError(f"parser/handler mismatch: {sorted(sub.choices.keys() ^ HANDLERS.keys())}")
    for name, handler in HANDLERS.items():
        if handler.mutates:
            sub.choices[name].add_argument("--dry-run", action="store_true")
            sub.choices[name].add_argument("--backup", action="store_true")
    return p


def run(argv=None):
    from .session import execute
    args = build_parser().parse_args(argv)
    return execute(args, HANDLERS[args.action])


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        out = {"ok": True, **run(argv)}
        code = 0
    except SheetError as e:
        out, code = {"ok": False, "error": str(e), **e.extra}, 1
    except Exception as e:
        out, code = {"ok": False, "error": f"{type(e).__name__}: {e}"}, 1
    print(json.dumps(out, ensure_ascii=False, default=str))
    return code
