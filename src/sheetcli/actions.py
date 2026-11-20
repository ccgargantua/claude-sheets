import csv
import io
import json
import os

from .common import (MAX_CELLS, SheetError, autotype, cell_ref, check_size,
                     col_to_idx, normalize_color, overlaps, parse_cell,
                     parse_range, range_str)
from .store import fmt_of, new_book, open_book, save_book


def _used_range(sheet):
    return (1, 1, sheet.max_row, sheet.max_col) if sheet.max_row else None


def _check_scalar(v):
    if v is not None and not isinstance(v, (str, int, float, bool)):
        raise SheetError(f"unsupported cell value in --data: {v!r}")
    return v


def _parse_data(s):
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise SheetError(f"--data is not valid JSON: {e}")
    if not isinstance(data, list) or not all(isinstance(r, list) for r in data):
        raise SheetError("--data must be a 2D JSON array")
    if sum(len(r) for r in data) > MAX_CELLS:
        raise SheetError(f"--data too large (max {MAX_CELLS} cells)")
    return [[_check_scalar(v) for v in r] for r in data]


def _put(sheet, row, col, data):
    for i, r in enumerate(data):
        for j, v in enumerate(r):
            sheet.set(row + i, col + j, v)
    width = max((len(r) for r in data), default=0)
    return range_str((row, col, row + max(len(data), 1) - 1, col + max(width, 1) - 1))


def _load(args):
    book = open_book(args.file)
    return book, book.sheet(args.sheet)


def info(a):
    book = open_book(a.file)
    return {"file": a.file, "format": book.fmt, "size": os.path.getsize(a.file),
            "sheets": [{"name": s.name, "rows": s.max_row, "cols": s.max_col} for s in book.sheets]}


def read(a):
    _, s = _load(a)
    rng = parse_range(a.range) if a.range else _used_range(s)
    if rng is None:
        data = []
    else:
        check_size(rng)
        r1, c1, r2, c2 = rng
        data = [[s.get(r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
    out = {"sheet": s.name, "range": range_str(rng) if rng else None}
    if a.as_ == "csv":
        buf = io.StringIO()
        csv.writer(buf, lineterminator="\n").writerows(
            [["" if v is None else v for v in row] for row in data])
        out["csv"] = buf.getvalue()
    else:
        out["data"] = data
    return out


def write(a):
    book, s = _load(a)
    r, c = parse_cell(a.cell)
    s.set(r, c, autotype(a.value))
    save_book(book, a.file)
    return {"sheet": s.name, "cell": cell_ref(r, c)}


def write_range(a):
    book, s = _load(a)
    r, c = parse_cell(a.start)
    rng = _put(s, r, c, _parse_data(a.data))
    save_book(book, a.file)
    return {"sheet": s.name, "range": rng}


def append(a):
    book, s = _load(a)
    data = _parse_data(a.data)
    row = s.max_row + 1
    rng = _put(s, row, 1, data)
    save_book(book, a.file)
    return {"sheet": s.name, "row": row, "range": rng}


def create(a):
    names = [n.strip() for n in a.sheets.split(",")]
    if os.path.exists(a.file):
        raise SheetError(f"file already exists: {a.file}")
    book = new_book(a.file, names)
    save_book(book, a.file)
    return {"file": a.file, "sheets": book.names()}


def add_sheet(a):
    book = open_book(a.file)
    book.add_sheet(a.name)
    save_book(book, a.file)
    return {"sheets": book.names()}


def delete_sheet(a):
    book = open_book(a.file)
    book.remove_sheet(a.name)
    save_book(book, a.file)
    return {"sheets": book.names()}


def rename_sheet(a):
    book = open_book(a.file)
    book.rename_sheet(a.name, a.new_name)
    save_book(book, a.file)
    return {"sheets": book.names()}


def _rows_op(a, op):
    if a.at < 1 or a.count < 1:
        raise SheetError("--at and --count must be >= 1")
    book, s = _load(a)
    getattr(s, op)(a.at, a.count)
    save_book(book, a.file)
    return {"sheet": s.name, "at": a.at, "count": a.count}


def insert_rows(a):
    return _rows_op(a, "insert_rows")


def delete_rows(a):
    return _rows_op(a, "delete_rows")


def find(a):
    _, s = _load(a)
    q = a.query if a.exact else a.query.lower()
    matches = []
    for r, c, v in s.items():
        text = str(v).lower() if isinstance(v, bool) else str(v)
        if (text == q) if a.exact else (q in text.lower()):
            matches.append({"cell": cell_ref(r, c), "value": v})
    return {"sheet": s.name, "count": len(matches), "matches": matches}


def _sort_key(v):
    if isinstance(v, bool):
        return (1, v)
    if isinstance(v, (int, float)):
        return (0, v)
    return (2, str(v).lower())


def sort(a):
    book, s = _load(a)
    col = col_to_idx(a.by)
    first = 2 if a.header else 1
    if s.max_row >= first:
        ncols = s.max_col
        rows = [[s.get(r, c) for c in range(1, ncols + 1)] for r in range(first, s.max_row + 1)]
        full = [r for r in rows if col > ncols or r[col - 1] is not None]
        empty = [r for r in rows if not (col > ncols or r[col - 1] is not None)]
        if col <= ncols:
            full.sort(key=lambda r: _sort_key(r[col - 1]), reverse=a.desc)
        for i, row in enumerate(full + empty):
            for c, v in enumerate(row, 1):
                s.set(first + i, c, v)
    save_book(book, a.file)
    return {"sheet": s.name, "by": a.by.upper(), "desc": a.desc}


def _copy_sheet(src, dst):
    for r, c, v in src.items():
        dst.set(r, c, v)
    for (r, c), fmt in src.style_items():
        dst.apply_format(r, c, r, c, fmt)
    for c, w in src.width_items():
        dst.set_col_width(c, w)
    for m in src.merges():
        dst.merge(m)


def convert(a):
    fmt_of(a.src)
    fmt_of(a.dst)
    if os.path.abspath(a.src) == os.path.abspath(a.dst):
        raise SheetError("src and dst are the same file")
    src = open_book(a.src)
    names = src.names()
    dst = new_book(a.dst, names[:1] if fmt_of(a.dst) == "csv" else names)
    skip_fmt = not dst.formatting
    for s, d in zip(src.sheets, dst.sheets):
        if skip_fmt:
            for r, c, v in s.items():
                d.set(r, c, v)
        else:
            _copy_sheet(s, d)
    save_book(dst, a.dst)
    out = {"src": a.src, "dst": a.dst, "sheets": dst.names()}
    if len(dst.sheets) < len(names):
        out["skipped_sheets"] = names[len(dst.sheets):]
    return out


def _build_fmt(a):
    fmt = {}
    for flag in ("bold", "italic", "underline"):
        if getattr(a, flag):
            fmt[flag] = True
    if a.font_size is not None:
        if a.font_size < 1:
            raise SheetError("--font-size must be >= 1")
        fmt["font_size"] = a.font_size
    if a.font_color:
        fmt["font_color"] = normalize_color(a.font_color)
    if a.fill:
        fmt["fill"] = normalize_color(a.fill)
    if a.number_format:
        fmt["number_format"] = a.number_format
    if a.align:
        fmt["align"] = a.align
    if not fmt:
        raise SheetError("no format options given")
    return fmt


def format_(a):
    book = open_book(a.file)
    book.require_formatting()
    fmt = _build_fmt(a)
    book.check_format(fmt)
    s = book.sheet(a.sheet)
    rng = parse_range(a.range)
    check_size(rng)
    s.apply_format(*rng, fmt)
    save_book(book, a.file)
    return {"sheet": s.name, "range": range_str(rng), "applied": sorted(fmt)}


def col_width(a):
    book = open_book(a.file)
    book.require_formatting()
    if a.width <= 0:
        raise SheetError("--width must be > 0")
    s = book.sheet(a.sheet)
    s.set_col_width(col_to_idx(a.col), a.width)
    save_book(book, a.file)
    return {"sheet": s.name, "col": a.col.upper(), "width": a.width}


def merge(a):
    book = open_book(a.file)
    book.require_formatting()
    s = book.sheet(a.sheet)
    rng = parse_range(a.range)
    if rng[0] == rng[2] and rng[1] == rng[3]:
        raise SheetError("merge range must span more than one cell")
    for m in s.merges():
        if overlaps(parse_range(m), rng):
            raise SheetError(f"overlaps existing merge {m}")
    s.merge(range_str(rng))
    save_book(book, a.file)
    return {"sheet": s.name, "merged": range_str(rng)}


def unmerge(a):
    book = open_book(a.file)
    book.require_formatting()
    s = book.sheet(a.sheet)
    before = len(s.merges())
    s.unmerge(range_str(parse_range(a.range)))
    save_book(book, a.file)
    return {"sheet": s.name, "unmerged": before - len(s.merges())}


ACTIONS = {
    "info": info, "read": read, "write": write, "write-range": write_range,
    "append": append, "create": create, "add-sheet": add_sheet,
    "delete-sheet": delete_sheet, "rename-sheet": rename_sheet,
    "insert-rows": insert_rows, "delete-rows": delete_rows, "find": find,
    "sort": sort, "convert": convert, "format": format_,
    "col-width": col_width, "merge": merge, "unmerge": unmerge,
}
