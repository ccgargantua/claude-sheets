import argparse
import json
import sys

from .actions import ACTIONS
from .common import SheetError


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(json.dumps({"ok": False, "error": message}))
        sys.exit(1)


def build_parser():
    p = _Parser(prog="sheet", description="Spreadsheet CLI (.xlsx, .ods, .csv); JSON output")
    sub = p.add_subparsers(dest="action", required=True, parser_class=_Parser)

    def cmd(name, *positional):
        sp = sub.add_parser(name)
        for pos in positional or ("file",):
            sp.add_argument(pos)
        return sp

    def sheet_opt(sp):
        sp.add_argument("--sheet")
        return sp

    cmd("info")
    sp = sheet_opt(cmd("read"))
    sp.add_argument("--range")
    sp.add_argument("--as", dest="as_", choices=["json", "csv"], default="json")
    sp = sheet_opt(cmd("write"))
    sp.add_argument("--cell", required=True)
    sp.add_argument("--value", required=True)
    sp = sheet_opt(cmd("write-range"))
    sp.add_argument("--start", required=True)
    sp.add_argument("--data", required=True)
    sp = sheet_opt(cmd("append"))
    sp.add_argument("--data", required=True)
    cmd("create").add_argument("--sheets", default="Sheet1")
    cmd("add-sheet").add_argument("--name", required=True)
    cmd("delete-sheet").add_argument("--name", required=True)
    sp = cmd("rename-sheet")
    sp.add_argument("--name", required=True)
    sp.add_argument("--new-name", required=True)
    for name in ("insert-rows", "delete-rows"):
        sp = sheet_opt(cmd(name))
        sp.add_argument("--at", type=int, required=True)
        sp.add_argument("--count", type=int, default=1)
    sp = sheet_opt(cmd("find"))
    sp.add_argument("--query", required=True)
    sp.add_argument("--exact", action="store_true")
    sp = sheet_opt(cmd("sort"))
    sp.add_argument("--by", required=True)
    sp.add_argument("--desc", action="store_true")
    sp.add_argument("--header", action="store_true")
    cmd("convert", "src", "dst")
    sp = sheet_opt(cmd("format"))
    sp.add_argument("--range", required=True)
    for flag in ("bold", "italic", "underline"):
        sp.add_argument(f"--{flag}", action="store_true")
    sp.add_argument("--font-size", type=int)
    sp.add_argument("--font-color")
    sp.add_argument("--fill")
    sp.add_argument("--number-format")
    sp.add_argument("--align", choices=["left", "center", "right"])
    sp = sheet_opt(cmd("col-width"))
    sp.add_argument("--col", required=True)
    sp.add_argument("--width", type=float, required=True)
    for name in ("merge", "unmerge"):
        sheet_opt(cmd(name)).add_argument("--range", required=True)
    return p


def run(argv=None):
    args = build_parser().parse_args(argv)
    return ACTIONS[args.action](args)


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
        out, code = {"ok": False, "error": str(e)}, 1
    except Exception as e:
        out, code = {"ok": False, "error": f"{type(e).__name__}: {e}"}, 1
    print(json.dumps(out, ensure_ascii=False, default=str))
    return code
