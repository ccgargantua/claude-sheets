import operator
import re

from ..cells import cell_range, read_grid, used_range
from ..common import SheetError, cell_ref, check_size, col_to_idx, idx_to_col, parse_range, range_str
from ..document import props
from .base import Handler, cmd, with_sheet


def register(sub):
    sp = with_sheet(cmd(sub, "find"))
    sp.add_argument("--query", required=True)
    sp.add_argument("--exact", action="store_true")
    sp = with_sheet(cmd(sub, "sort"))
    sp.add_argument("--by", required=True)
    sp.add_argument("--desc", action="store_true")
    sp.add_argument("--header", action="store_true")
    sp = with_sheet(cmd(sub, "filter"))
    sp.add_argument("--where", action="append", required=True)
    sp.add_argument("--header", action="store_true")
    sp = with_sheet(cmd(sub, "dedupe"))
    sp.add_argument("--cols")
    sp.add_argument("--header", action="store_true")
    with_sheet(cmd(sub, "stats")).add_argument("--range", required=True)


def find(doc, a):
    sheet = doc.sheet(a.sheet)
    used = used_range(sheet)
    query = a.query if a.exact else a.query.lower()
    matches = []
    if used:
        for i, row in enumerate(read_grid(doc, sheet, used)):
            for j, v in enumerate(row):
                if v is None:
                    continue
                text = str(v).lower() if isinstance(v, bool) else str(v)
                if (text == query) if a.exact else (query in text.lower()):
                    matches.append({"cell": cell_ref(i + 1, j + 1), "value": v})
    return {"sheet": sheet.Name, "count": len(matches), "matches": matches}


def sort(doc, a):
    import uno
    sheet = doc.sheet(a.sheet)
    col = col_to_idx(a.by)
    used = used_range(sheet)
    first = 2 if a.header else 1
    if used and used[2] >= first and col <= used[3]:
        field = uno.createUnoStruct("com.sun.star.table.TableSortField")
        field.Field, field.IsAscending, field.IsCaseSensitive = col - 1, not a.desc, False
        fields = uno.Any("[]com.sun.star.table.TableSortField", (field,))
        cell_range(sheet, (first, 1, used[2], used[3])).sort(
            props(SortFields=fields, ContainsHeader=False, IsSortColumns=False))
    return {"sheet": sheet.Name, "by": a.by.upper(), "desc": a.desc}


_WHERE = re.compile(r"\s*([A-Za-z]{1,3})\s*(==|!=|>=|<=|>|<|\s(?:contains)\s)\s*(.*)", re.S)
_OPS = {"==": operator.eq, "!=": operator.ne, ">": operator.gt, "<": operator.lt,
        ">=": operator.ge, "<=": operator.le}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _text(v):
    if v is None:
        return ""
    return str(v).lower()


def _to_num(s):
    try:
        return float(s)
    except ValueError:
        return None


def _parse_where(expr):
    m = _WHERE.fullmatch(expr)
    if not m:
        raise SheetError(f"bad --where: {expr!r} (COLOP VALUE, ops == != > < >= <= contains)")
    col, op, value = m[1], m[2].strip(), m[3].strip()
    num = _to_num(value)
    needle = value.lower()
    if op == "contains":
        test = lambda cell: needle in _text(cell)
    else:
        fn = _OPS[op]
        ordering = op not in ("==", "!=")

        def test(cell):
            if num is None:
                return fn(_text(cell), needle)
            if _is_num(cell):
                return fn(float(cell), num)
            return False if ordering else fn(_text(cell), needle)
    return col_to_idx(col) - 1, test


def filter_(doc, a):
    sheet = doc.sheet(a.sheet)
    conds = [_parse_where(w) for w in a.where]
    used = used_range(sheet)
    grid = read_grid(doc, sheet, used) if used else []
    width = used[3] if used else 0
    for col, _ in conds:
        if col >= width and grid:
            raise SheetError(f"column beyond used range: {idx_to_col(col + 1)}")
    out = {"sheet": sheet.Name}
    if a.header and grid:
        out["header"] = grid[0]
    first = 1 if a.header else 0
    rows = [{"row": i + 1, "values": row} for i, row in enumerate(grid) if i >= first
            and all(test(row[col]) for col, test in conds)]
    return {**out, "count": len(rows), "rows": rows}


def dedupe(doc, a):
    sheet = doc.sheet(a.sheet)
    used = used_range(sheet)
    removed = []
    if used:
        grid = read_grid(doc, sheet, used)
        cols = sorted({col_to_idx(c.strip()) - 1 for c in a.cols.split(",")}) if a.cols \
            else list(range(used[3]))
        if cols[-1] >= used[3]:
            raise SheetError("--cols beyond used range")
        seen = set()
        for i in range(1 if a.header else 0, len(grid)):
            key = tuple(grid[i][c] for c in cols)
            if key in seen:
                removed.append(i + 1)
            seen.add(key)
        for row in reversed(removed):
            sheet.Rows.removeByIndex(row - 1, 1)
    return {"sheet": sheet.Name, "removed": len(removed)}


def stats(doc, a):
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    check_size(rng)
    values = [v for row in read_grid(doc, sheet, rng) for v in row if v is not None]
    nums = [v for v in values if _is_num(v)]
    return {"sheet": sheet.Name, "range": range_str(rng), "count": len(values),
            "numeric_count": len(nums), "sum": sum(nums) if nums else 0,
            "mean": sum(nums) / len(nums) if nums else None,
            "min": min(nums) if nums else None, "max": max(nums) if nums else None}


HANDLERS = {
    "find": Handler(find),
    "sort": Handler(sort, mutates=True),
    "filter": Handler(filter_),
    "dedupe": Handler(dedupe, mutates=True),
    "stats": Handler(stats),
}
