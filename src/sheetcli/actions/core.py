import argparse
import csv
import io
import json
import os

from ..cells import check_data_size, read_grid, used_range, write_grid
from ..common import (SheetError, autotype, cell_ref, check_size, fmt_of, parse_cell,
                      parse_range, range_str)
from ..document import (backup_file, check_input_file, check_new_sheets, new_doc, open_doc,
                        store)
from .base import Handler, cmd, with_sheet

BATCH_DISALLOWED = {"batch", "create", "convert", "stop", "status"}
BATCH_RESERVED = {"file", "dry_run", "backup"}


def register(sub):
    cmd(sub, "info")
    sp = with_sheet(cmd(sub, "read"))
    sp.add_argument("--range")
    sp.add_argument("--as", dest="as_", choices=["json", "csv"], default="json")
    sp.add_argument("--formulas", action="store_true")
    sp = with_sheet(cmd(sub, "write"))
    sp.add_argument("--cell", required=True)
    sp.add_argument("--value", required=True)
    sp = with_sheet(cmd(sub, "write-range"))
    sp.add_argument("--start", required=True)
    sp.add_argument("--data", required=True)
    sp = with_sheet(cmd(sub, "append"))
    sp.add_argument("--data", required=True)
    cmd(sub, "create").add_argument("--sheets", default="Sheet1")
    cmd(sub, "convert", ("src", "dst"))
    batch = cmd(sub, "batch")
    ops = batch.add_mutually_exclusive_group(required=True)
    ops.add_argument("--ops")
    ops.add_argument("--ops-file")
    cmd(sub, "recalc")
    cmd(sub, "status", ())
    cmd(sub, "stop", ())


def parse_data(s):
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise SheetError(f"--data is not valid JSON: {e}")
    if not isinstance(data, list) or not all(isinstance(r, list) for r in data):
        raise SheetError("--data must be a 2D JSON array")
    for row in data:
        for v in row:
            if v is not None and not isinstance(v, (str, int, float, bool)):
                raise SheetError(f"unsupported cell value in --data: {v!r}")
    check_data_size(data)
    return data


def put(doc, sheet, row, col, data):
    write_grid(doc, sheet, row, col, data)
    width = max((len(r) for r in data), default=0)
    return range_str((row, col, row + max(len(data), 1) - 1, col + max(width, 1) - 1))


def info(doc, a):
    sheets = []
    for name in doc.sheet_names():
        used = used_range(doc.sheet(name))
        sheets.append({"name": name, "rows": used[2] if used else 0, "cols": used[3] if used else 0})
    return {"file": a.file, "format": doc.fmt, "size": os.path.getsize(a.file), "sheets": sheets}


def read(doc, a):
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range) if a.range else used_range(sheet)
    data = []
    if rng:
        check_size(rng)
        data = read_grid(doc, sheet, rng, a.formulas)
    out = {"sheet": sheet.Name, "range": range_str(rng) if rng else None}
    if a.as_ == "csv":
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(
            [["" if v is None else v for v in row] for row in data])
        out["csv"] = buf.getvalue()
    else:
        out["data"] = data
    return out


def write(doc, a):
    sheet = doc.sheet(a.sheet)
    r, c = parse_cell(a.cell)
    write_grid(doc, sheet, r, c, [[autotype(a.value)]])
    return {"sheet": sheet.Name, "cell": cell_ref(r, c)}


def write_range(doc, a):
    sheet = doc.sheet(a.sheet)
    r, c = parse_cell(a.start)
    return {"sheet": sheet.Name, "range": put(doc, sheet, r, c, parse_data(a.data))}


def append(doc, a):
    sheet = doc.sheet(a.sheet)
    data = parse_data(a.data)
    used = used_range(sheet)
    row = (used[2] if used else 0) + 1
    return {"sheet": sheet.Name, "row": row, "range": put(doc, sheet, row, 1, data)}


def recalc(doc, a):
    doc.recalc()
    return {"recalculated": True}


def create(a):
    from ..uno_daemon import connection
    names = [n.strip() for n in a.sheets.split(",")]
    check_new_sheets(a.file, names)
    if os.path.exists(a.file):
        raise SheetError(f"file already exists: {a.file}")
    with connection() as desktop, new_doc(desktop, a.file, names) as doc:
        if not a.dry_run:
            doc.save()
    return {"file": a.file, "sheets": names, **({"dry_run": True} if a.dry_run else {})}


def convert(a):
    from ..uno_daemon import connection
    src_fmt, dst_fmt = fmt_of(a.src), fmt_of(a.dst)
    if os.path.abspath(a.src) == os.path.abspath(a.dst):
        raise SheetError("src and dst are the same file")
    check_input_file(a.src)
    out = {"src": a.src, "dst": a.dst}
    with connection() as desktop, open_doc(desktop, a.src) as doc:
        names = doc.sheet_names()
        kept = names[:1] if dst_fmt == "csv" else names
        if not a.dry_run:
            if a.backup and os.path.exists(a.dst):
                out["backup"] = backup_file(a.dst)
            store(doc.comp, a.dst, dst_fmt)
    out["sheets"] = kept
    if len(kept) < len(names):
        out["skipped_sheets"] = names[len(kept):]
    if a.dry_run:
        out["dry_run"] = True
    return out


def _op_argv(subparsers, index, op, file):
    action = op.get("action") if isinstance(op, dict) else None
    if action not in subparsers:
        raise SheetError(f"op {index}: unknown action {action!r}", op=index)
    if action in BATCH_DISALLOWED:
        raise SheetError(f"op {index} ({action}): not allowed in batch", op=index, action=action)
    reserved = BATCH_RESERVED & op.keys()
    if reserved:
        raise SheetError(f"op {index} ({action}): {sorted(reserved)} not allowed in an op",
                         op=index, action=action)
    repeatable = {a.dest for a in subparsers[action]._actions
                  if isinstance(a, argparse._AppendAction)}
    argv = [action, file]
    for key, value in op.items():
        if key == "action" or value is None or value is False:
            continue
        flag = "--" + key.replace("_", "-")
        if value is True:
            argv.append(flag)
        elif key in repeatable:
            argv += [f"{flag}={v}" for v in (value if isinstance(value, list) else [value])]
        elif isinstance(value, (list, dict)):
            argv.append(f"{flag}={json.dumps(value)}")
        else:
            argv.append(f"{flag}={value}")
    return argv


def _load_ops(a):
    try:
        text = open(a.ops_file, encoding="utf-8").read() if a.ops_file else a.ops
        ops = json.loads(text)
    except (OSError, json.JSONDecodeError) as e:
        raise SheetError(f"cannot read ops: {e}")
    if not isinstance(ops, list) or not ops:
        raise SheetError("ops must be a non-empty JSON list")
    return ops


def batch(a):
    from ..cli import build_parser
    from ..session import run_ops
    from . import HANDLERS
    parser = build_parser(raise_errors=True)
    subparsers = next(act for act in parser._actions if act.dest == "action").choices
    parsed = []
    for i, op in enumerate(_load_ops(a)):
        argv = _op_argv(subparsers, i, op, a.file)
        try:
            args = parser.parse_args(argv)
        except SheetError as e:
            raise SheetError(f"op {i} ({op['action']}): {e}", op=i, action=op["action"])
        parsed.append((args, HANDLERS[args.action]))
    results, extra = run_ops(a.file, parsed, a.dry_run, a.backup, indexed=True)
    return {"count": len(results), "results": results, **extra}


def status(a):
    from ..uno_daemon import status as daemon_status
    return daemon_status()


def stop(a):
    from ..uno_daemon import stop as daemon_stop
    return daemon_stop()


HANDLERS = {
    "info": Handler(info),
    "read": Handler(read),
    "write": Handler(write, mutates=True),
    "write-range": Handler(write_range, mutates=True),
    "append": Handler(append, mutates=True),
    "create": Handler(create, mutates=True, free=True),
    "convert": Handler(convert, mutates=True, free=True),
    "batch": Handler(batch, mutates=True, free=True),
    "recalc": Handler(recalc, mutates=True),
    "status": Handler(status, free=True),
    "stop": Handler(stop, free=True),
}
