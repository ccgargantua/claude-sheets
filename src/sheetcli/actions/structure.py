import math

from ..cells import cell_range, col_span, row_span
from ..common import (SheetError, check_size, check_sheet_name, col_to_idx, parse_cell, parse_range,
                      range_str)
from .base import Handler, cmd, with_sheet


def register(sub):
    cmd(sub, "add-sheet").add_argument("--name", required=True)
    cmd(sub, "delete-sheet").add_argument("--name", required=True)
    sp = cmd(sub, "rename-sheet")
    sp.add_argument("--name", required=True)
    sp.add_argument("--new-name", required=True)
    for name in ("insert-rows", "delete-rows"):
        sp = with_sheet(cmd(sub, name))
        sp.add_argument("--at", type=int, required=True)
        sp.add_argument("--count", type=int, default=1)
    for name in ("insert-cols", "delete-cols"):
        sp = with_sheet(cmd(sub, name))
        sp.add_argument("--at", required=True)
        sp.add_argument("--count", type=int, default=1)
    sp = with_sheet(cmd(sub, "clear"))
    sp.add_argument("--range", required=True)
    sp.add_argument("--what", choices=["all", "contents", "formats"], default="all")
    for name in ("copy-range", "move-range"):
        sp = with_sheet(cmd(sub, name))
        sp.add_argument("--src", required=True)
        sp.add_argument("--dst", required=True)
        sp.add_argument("--dst-sheet")
    sp = with_sheet(cmd(sub, "fill"))
    sp.add_argument("--range", required=True)
    sp.add_argument("--mode", choices=["down", "right", "series"], default="down")
    sp.add_argument("--step", type=float, default=1.0)
    sp = cmd(sub, "copy-sheet")
    sp.add_argument("--name", required=True)
    sp.add_argument("--new-name", required=True)
    sp.add_argument("--position", type=int)
    sp = cmd(sub, "move-sheet")
    sp.add_argument("--name", required=True)
    sp.add_argument("--position", type=int, required=True)
    for name in ("hide-sheet", "show-sheet"):
        cmd(sub, name).add_argument("--name", required=True)
    for name in ("hide-rows", "show-rows"):
        with_sheet(cmd(sub, name)).add_argument("--rows", required=True)
    for name in ("hide-cols", "show-cols"):
        with_sheet(cmd(sub, name)).add_argument("--cols", required=True)
    with_sheet(cmd(sub, "freeze")).add_argument("--cell", required=True)
    with_sheet(cmd(sub, "unfreeze"))
    sp = with_sheet(cmd(sub, "autofilter"))
    sp.add_argument("--range")
    sp.add_argument("--off", action="store_true")


def _check_free_name(doc, name):
    check_sheet_name(name)
    if name.lower() in (n.lower() for n in doc.sheet_names()):
        raise SheetError(f"sheet already exists: {name}")


def add_sheet(doc, a):
    _check_free_name(doc, a.name)
    doc.sheets.insertNewByName(a.name, doc.sheets.Count)
    return {"sheets": doc.sheet_names()}


def delete_sheet(doc, a):
    doc.sheet(a.name)
    if doc.sheets.Count == 1:
        raise SheetError("cannot delete the only sheet")
    doc.sheets.removeByName(a.name)
    return {"sheets": doc.sheet_names()}


def rename_sheet(doc, a):
    sheet = doc.sheet(a.name)
    if a.new_name.lower() != a.name.lower():
        _check_free_name(doc, a.new_name)
    else:
        check_sheet_name(a.new_name)
    sheet.Name = a.new_name
    return {"sheets": doc.sheet_names()}


def _rows(doc, a, remove):
    if a.at < 1 or a.count < 1:
        raise SheetError("--at and --count must be >= 1")
    sheet = doc.sheet(a.sheet)
    (sheet.Rows.removeByIndex if remove else sheet.Rows.insertByIndex)(a.at - 1, a.count)
    return {"sheet": sheet.Name, "at": a.at, "count": a.count}


def insert_rows(doc, a):
    return _rows(doc, a, remove=False)


def delete_rows(doc, a):
    return _rows(doc, a, remove=True)


def _cols(doc, a, remove):
    if a.count < 1:
        raise SheetError("--at and --count must be >= 1")
    at = col_to_idx(a.at)
    sheet = doc.sheet(a.sheet)
    (sheet.Columns.removeByIndex if remove else sheet.Columns.insertByIndex)(at - 1, a.count)
    return {"sheet": sheet.Name, "at": a.at.upper(), "count": a.count}


def insert_cols(doc, a):
    return _cols(doc, a, remove=False)


def delete_cols(doc, a):
    return _cols(doc, a, remove=True)


# UNO CellFlags: VALUE 1, DATETIME 2, STRING 4, ANNOTATION 8, FORMULA 16, HARDATTR 32, EDITATTR 256
CLEAR_FLAGS = {"contents": 1 | 2 | 4 | 16, "formats": 32 | 256, "all": 1 | 2 | 4 | 8 | 16 | 32 | 256}


def clear(doc, a):
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    cell_range(sheet, rng).clearContents(CLEAR_FLAGS[a.what])
    return {"sheet": sheet.Name, "range": range_str(rng), "what": a.what}


def _transfer(doc, a, move):
    src_sheet = doc.sheet(a.sheet)
    dst_sheet = doc.sheet(a.dst_sheet) if a.dst_sheet else src_sheet
    src = parse_range(a.src)
    check_size(src)
    row, col = parse_cell(a.dst)
    from com.sun.star.table import CellAddress
    dst = CellAddress(dst_sheet.RangeAddress.Sheet, col - 1, row - 1)
    src_addr = cell_range(src_sheet, src).RangeAddress
    (src_sheet.moveRange if move else src_sheet.copyRange)(dst, src_addr)
    return {"sheet": src_sheet.Name, "src": range_str(src), "dst_sheet": dst_sheet.Name, "dst": a.dst.upper()}


def copy_range(doc, a):
    return _transfer(doc, a, move=False)


def move_range(doc, a):
    return _transfer(doc, a, move=True)


def fill(doc, a):
    import uno
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    check_size(rng)
    r1, c1, r2, c2 = rng
    down = a.mode == "down" or (a.mode == "series" and r2 > r1)
    if (r2 - r1 if down else c2 - c1) < 1:
        raise SheetError(f"range must span at least 2 {'rows' if down else 'columns'}")
    mode, step, end = "SIMPLE", 1.0, 0.0
    if a.mode == "series":
        mode, step = "LINEAR", a.step
        end = math.copysign(1e300, step)
        firsts = [(r1, c) for c in range(c1, c2 + 1)] if down else [(r, c1) for r in range(r1, r2 + 1)]
        for r, c in firsts:
            if sheet.getCellByPosition(c - 1, r - 1).Type.value != "VALUE":
                raise SheetError("series needs numeric first cells")
    direction = uno.Enum("com.sun.star.sheet.FillDirection", "TO_BOTTOM" if down else "TO_RIGHT")
    fill_mode = uno.Enum("com.sun.star.sheet.FillMode", mode)
    day = uno.Enum("com.sun.star.sheet.FillDateMode", "FILL_DATE_DAY")
    cell_range(sheet, rng).fillSeries(direction, fill_mode, day, step, end)
    return {"sheet": sheet.Name, "range": range_str(rng), "mode": a.mode}


def _position(value, count, flag):
    if not 1 <= value <= count:
        raise SheetError(f"{flag} must be between 1 and {count}")
    return value - 1


def copy_sheet(doc, a):
    doc.sheet(a.name)
    _check_free_name(doc, a.new_name)
    count = doc.sheets.Count
    pos = count if a.position is None else _position(a.position, count + 1, "--position")
    doc.sheets.copyByName(a.name, a.new_name, pos)
    return {"sheets": doc.sheet_names()}


def move_sheet(doc, a):
    doc.sheet(a.name)
    target = _position(a.position, doc.sheets.Count, "--position")
    current = doc.sheet_names().index(a.name)
    doc.sheets.moveByName(a.name, target + 1 if current < target else target)
    return {"sheets": doc.sheet_names()}


def _visible_sheets(doc):
    return [n for n in doc.sheet_names() if doc.sheet(n).IsVisible]


def hide_sheet(doc, a):
    sheet = doc.sheet(a.name)
    visible = _visible_sheets(doc)
    if sheet.IsVisible and len(visible) == 1:
        raise SheetError("cannot hide the last visible sheet")
    controller = doc.comp.getCurrentController()
    if controller is not None and controller.ActiveSheet.Name == a.name:
        controller.setActiveSheet(doc.sheet(next(n for n in visible if n != a.name)))
    sheet.IsVisible = False
    return {"sheets": doc.sheet_names(), "hidden": [n for n in doc.sheet_names() if not doc.sheet(n).IsVisible]}


def show_sheet(doc, a):
    doc.sheet(a.name).IsVisible = True
    return {"sheets": doc.sheet_names(), "hidden": [n for n in doc.sheet_names() if not doc.sheet(n).IsVisible]}


def _set_visible(doc, a, visible):
    sheet = doc.sheet(a.sheet)
    key = "rows" if hasattr(a, "rows") else "cols"
    target, first, last = (row_span if key == "rows" else col_span)(sheet, getattr(a, key))
    target.IsVisible = visible
    return {"sheet": sheet.Name, key: f"{first}:{last}", "visible": visible}


def hide_rows(doc, a):
    return _set_visible(doc, a, False)


def show_rows(doc, a):
    return _set_visible(doc, a, True)


def hide_cols(doc, a):
    return _set_visible(doc, a, False)


def show_cols(doc, a):
    return _set_visible(doc, a, True)


def _freeze_at(doc, sheet, col, row):
    controller = doc.comp.getCurrentController()
    previous = controller.ActiveSheet
    controller.setActiveSheet(sheet)
    controller.freezeAtPosition(col, row)
    controller.setActiveSheet(previous)


def freeze(doc, a):
    sheet = doc.sheet(a.sheet)
    row, col = parse_cell(a.cell)
    if (row, col) == (1, 1):
        raise SheetError("freezing at A1 freezes nothing; use unfreeze")
    _freeze_at(doc, sheet, col - 1, row - 1)
    return {"sheet": sheet.Name, "frozen_rows": row - 1, "frozen_cols": col - 1}


def unfreeze(doc, a):
    sheet = doc.sheet(a.sheet)
    _freeze_at(doc, sheet, 0, 0)
    return {"sheet": sheet.Name}


def _autofilter_names(doc, sheet):
    ranges = doc.comp.DatabaseRanges
    index = sheet.RangeAddress.Sheet
    return [n for n in ranges.ElementNames
            if ranges.getByName(n).DataArea.Sheet == index and ranges.getByName(n).AutoFilter]


def autofilter(doc, a):
    sheet = doc.sheet(a.sheet)
    if a.off == bool(a.range):
        raise SheetError("give exactly one of --range or --off")
    ranges = doc.comp.DatabaseRanges
    existing = _autofilter_names(doc, sheet)
    for name in existing:
        ranges.removeByName(name)
    if a.off:
        return {"sheet": sheet.Name, "autofilter": False, "removed": len(existing)}
    rng = parse_range(a.range)
    check_size(rng)
    taken = set(ranges.ElementNames)
    name = next(f"autofilter_{i}" for i in range(1, len(taken) + 2) if f"autofilter_{i}" not in taken)
    ranges.addNewByName(name, cell_range(sheet, rng).RangeAddress)
    ranges.getByName(name).AutoFilter = True
    return {"sheet": sheet.Name, "autofilter": True, "range": range_str(rng)}


HANDLERS = {
    "add-sheet": Handler(add_sheet, mutates=True, rich=True),
    "delete-sheet": Handler(delete_sheet, mutates=True, rich=True),
    "rename-sheet": Handler(rename_sheet, mutates=True, rich=True),
    "insert-rows": Handler(insert_rows, mutates=True),
    "delete-rows": Handler(delete_rows, mutates=True),
    "insert-cols": Handler(insert_cols, mutates=True),
    "delete-cols": Handler(delete_cols, mutates=True),
    "clear": Handler(clear, mutates=True),
    "copy-range": Handler(copy_range, mutates=True),
    "move-range": Handler(move_range, mutates=True),
    "fill": Handler(fill, mutates=True),
    "copy-sheet": Handler(copy_sheet, mutates=True, rich=True),
    "move-sheet": Handler(move_sheet, mutates=True, rich=True),
    "hide-sheet": Handler(hide_sheet, mutates=True, rich=True),
    "show-sheet": Handler(show_sheet, mutates=True, rich=True),
    "hide-rows": Handler(hide_rows, mutates=True, rich=True),
    "show-rows": Handler(show_rows, mutates=True, rich=True),
    "hide-cols": Handler(hide_cols, mutates=True, rich=True),
    "show-cols": Handler(show_cols, mutates=True, rich=True),
    "freeze": Handler(freeze, mutates=True, rich=True),
    "unfreeze": Handler(unfreeze, mutates=True, rich=True),
    "autofilter": Handler(autofilter, mutates=True, rich=True),
}
