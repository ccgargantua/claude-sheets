from datetime import datetime, timedelta

from .common import MAX_CELLS, SheetError, parse_col_span, parse_row_span

CONTENT = 1 | 2 | 4 | 16
CONTENT_AND_NOTES = CONTENT | 8
LOGICAL, DATE_OR_TIME = 1024, 6


def cell_range(sheet, rng):
    r1, c1, r2, c2 = rng
    return sheet.getCellRangeByPosition(c1 - 1, r1 - 1, c2 - 1, r2 - 1)


def row_span(sheet, span):
    """(Rows collection, first, last) for a row span like '2:5'."""
    first, last = parse_row_span(span)
    return sheet.getCellRangeByPosition(0, first - 1, 0, last - 1).Rows, first, last


def col_span(sheet, span):
    """(Columns collection, first, last) for a column span like 'B:D'."""
    first, last = parse_col_span(span)
    return sheet.getCellRangeByPosition(first - 1, 0, last - 1, 0).Columns, first, last


def used_range(sheet):
    addrs = sheet.queryContentCells(CONTENT).RangeAddresses
    if not addrs:
        return None
    return 1, 1, max(a.EndRow for a in addrs) + 1, max(a.EndColumn for a in addrs) + 1


def _iter_addresses(addrs):
    for a in addrs:
        for r in range(a.StartRow, a.EndRow + 1):
            for c in range(a.StartColumn, a.EndColumn + 1):
                yield r, c


def _intish(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _iso(doc, value, kind):
    nd = doc.comp.NullDate
    base = datetime(nd.Year, nd.Month, nd.Day) + timedelta(days=value)
    if kind & 2 and kind & 4:
        return base.isoformat(timespec="seconds")
    if kind & 2:
        return base.date().isoformat()
    return (datetime(1970, 1, 1) + timedelta(days=value % 1)).time().isoformat(timespec="seconds")


def _special_formats(doc, rng_obj):
    """Yield (row, col) offsets-free absolute cells with logical/date formats and their format type."""
    cache = {}
    ranges = rng_obj.getCellFormatRanges()
    for i in range(ranges.Count):
        fr = ranges.getByIndex(i)
        key = fr.NumberFormat
        if key not in cache:
            cache[key] = doc.number_format_type(key)
        kind = cache[key]
        if kind & LOGICAL or kind & DATE_OR_TIME:
            a = fr.RangeAddress
            for r in range(a.StartRow, a.EndRow + 1):
                for c in range(a.StartColumn, a.EndColumn + 1):
                    yield r, c, kind


def read_grid(doc, sheet, rng, formulas=False):
    r1, c1, r2, c2 = rng
    obj = cell_range(sheet, rng)
    data = [list(row) for row in obj.getDataArray()]

    def put(r, c, v):
        data[r - (r1 - 1)][c - (c1 - 1)] = v

    for r, c, kind in _special_formats(doc, obj):
        v = data[r - (r1 - 1)][c - (c1 - 1)]
        if isinstance(v, float):
            put(r, c, bool(v) if kind & LOGICAL else _iso(doc, v, kind))
    for r, c in _iter_addresses(obj.queryContentCells(16).RangeAddresses):
        cell = sheet.getCellByPosition(c, r)
        if formulas:
            text = doc.formula_text(cell)
            put(r, c, {"=TRUE()": True, "=FALSE()": False}.get(text, text))
        elif cell.getError():
            put(r, c, cell.String)
    return [[None if v == "" else _intish(v) for v in row] for row in data]


def check_data_size(data):
    if sum(len(r) for r in data) > MAX_CELLS:
        raise SheetError(f"--data too large (max {MAX_CELLS} cells)")


def write_grid(doc, sheet, row, col, data):
    """Write a 2D list at (row, col), 1-based. Strings stay text unless they start with '='."""
    height = len(data)
    width = max((len(r) for r in data), default=0)
    if not height or not width:
        return
    plain = [[""] * width for _ in range(height)]
    formulas, bools = [], []
    for i, r in enumerate(data):
        for j, v in enumerate(r):
            if isinstance(v, bool):
                bools.append((i, j, v))
            elif isinstance(v, str) and v.startswith("="):
                formulas.append((i, j, v))
            elif isinstance(v, (int, float)):
                plain[i][j] = float(v)
            elif v is not None:
                plain[i][j] = v
    cell_range(sheet, (row, col, row + height - 1, col + width - 1)).setDataArray(
        tuple(tuple(r) for r in plain))
    bool_key = doc.number_format("BOOLEAN") if bools else None
    for i, j, v in bools:
        cell = sheet.getCellByPosition(col - 1 + j, row - 1 + i)
        cell.setValue(1.0 if v else 0.0)
        cell.NumberFormat = bool_key
    for i, j, v in formulas:
        doc.set_formula(sheet.getCellByPosition(col - 1 + j, row - 1 + i), v)
