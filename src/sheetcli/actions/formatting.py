from ..cells import CONTENT_AND_NOTES, cell_range, col_span, row_span
from ..common import (SheetError, cell_ref, check_size, col_to_idx, normalize_color, parse_cell,
                      parse_range, range_str)
from ..document import props
from .base import Handler, cmd, with_sheet

# 1 character unit ~ 2.3 mm (Excel-like); UNO column Width is in 1/100 mm
COL_WIDTH_MM100_PER_CHAR = 230
BORDER_WIDTH_MM100 = 26
NO_LINE = 32767
VERT_NAMES = ("general", "top", "center", "bottom")
BORDER_SIDES = {
    "all": ("Top", "Bottom", "Left", "Right", "Horizontal", "Vertical"),
    "outline": ("Top", "Bottom", "Left", "Right"),
    "none": ("Top", "Bottom", "Left", "Right", "Horizontal", "Vertical"),
    "top": ("Top",), "bottom": ("Bottom",), "left": ("Left",), "right": ("Right",),
}
HORI = {"left": "LEFT", "center": "CENTER", "right": "RIGHT"}
VERT = {"top": 1, "center": 2, "bottom": 3}


def register(sub):
    sp = with_sheet(cmd(sub, "format"))
    sp.add_argument("--range", required=True)
    for flag in ("bold", "italic", "underline", "strike", "wrap",
                 "no-bold", "no-italic", "no-underline", "no-strike", "no-wrap"):
        sp.add_argument(f"--{flag}", action="store_true")
    sp.add_argument("--font-size", type=int)
    sp.add_argument("--font-name")
    sp.add_argument("--font-color")
    sp.add_argument("--fill")
    sp.add_argument("--number-format")
    sp.add_argument("--align", choices=["left", "center", "right"])
    sp.add_argument("--valign", choices=["top", "center", "bottom"])
    sp.add_argument("--border", choices=["all", "outline", "top", "bottom", "left", "right", "none"])
    sp.add_argument("--border-color")
    sp = with_sheet(cmd(sub, "col-width"))
    sp.add_argument("--col", required=True)
    sp.add_argument("--width", type=float, required=True)
    for name in ("merge", "unmerge"):
        with_sheet(cmd(sub, name)).add_argument("--range", required=True)
    sp = with_sheet(cmd(sub, "row-height"))
    sp.add_argument("--rows", required=True)
    sp.add_argument("--height", type=float, required=True)
    sp = with_sheet(cmd(sub, "autofit"))
    sp.add_argument("--cols")
    sp.add_argument("--rows")
    with_sheet(cmd(sub, "get-format")).add_argument("--cell", required=True)
    sp = with_sheet(cmd(sub, "cond-format"))
    sp.add_argument("--range", required=True)
    sp.add_argument("--condition", required=True,
                    choices=["gt", "lt", "ge", "le", "eq", "ne", "between", "contains", "formula"])
    sp.add_argument("--value", required=True)
    sp.add_argument("--value2")
    sp.add_argument("--fill")
    sp.add_argument("--font-color")
    sp.add_argument("--bold", action="store_true")
    with_sheet(cmd(sub, "cond-format-clear")).add_argument("--range", required=True)


def _toggles():
    import uno
    slant = lambda name: uno.Enum("com.sun.star.awt.FontSlant", name)
    return {
        "bold": ("CharWeight", 150.0, 100.0),
        "italic": ("CharPosture", slant("ITALIC"), slant("NONE")),
        "underline": ("CharUnderline", 1, 0),
        "strike": ("CharStrikeout", 1, 0),
        "wrap": ("IsTextWrapped", True, False),
    }


def _format_props(doc, a):
    """Returns ({UNO property: value}, applied option names)."""
    import uno
    p, applied = {}, []
    for key, (prop, on, off) in _toggles().items():
        want_on, want_off = getattr(a, key), getattr(a, f"no_{key}")
        if want_on and want_off:
            raise SheetError(f"--{key} and --no-{key} conflict")
        if want_on or want_off:
            p[prop] = on if want_on else off
            applied.append(key if want_on else f"no_{key}")
    if a.font_size is not None:
        if a.font_size < 1:
            raise SheetError("--font-size must be >= 1")
        p["CharHeight"] = float(a.font_size)
        applied.append("font_size")
    if a.font_name:
        p["CharFontName"] = a.font_name
        applied.append("font_name")
    if a.font_color:
        p["CharColor"] = int(normalize_color(a.font_color), 16)
        applied.append("font_color")
    if a.fill:
        p["CellBackColor"] = int(normalize_color(a.fill), 16)
        applied.append("fill")
    if a.number_format:
        p["NumberFormat"] = doc.number_format(a.number_format)
        applied.append("number_format")
    if a.align:
        p["HoriJustify"] = uno.Enum("com.sun.star.table.CellHoriJustify", HORI[a.align])
        applied.append("align")
    if a.valign:
        p["VertJustify"] = VERT[a.valign]
        applied.append("valign")
    return p, applied


def _apply_border(target, mode, color):
    import uno
    from com.sun.star.table import BorderLine2, TableBorder2
    line = BorderLine2()
    line.Color = int(color, 16)
    line.LineWidth = line.OuterLineWidth = 0 if mode == "none" else BORDER_WIDTH_MM100
    line.LineStyle = uno.getConstantByName(
        "com.sun.star.table.BorderLineStyle." + ("NONE" if mode == "none" else "SOLID"))
    border = TableBorder2()
    for side in ("Top", "Bottom", "Left", "Right", "Horizontal", "Vertical"):
        chosen = side in BORDER_SIDES[mode]
        setattr(border, f"Is{side}LineValid", chosen)
        if chosen:
            setattr(border, f"{side}Line", line)
    border.IsDistanceValid = False
    target.TableBorder2 = border


def format_(doc, a):
    props_, applied = _format_props(doc, a)
    if a.border_color and not a.border:
        raise SheetError("--border-color requires --border")
    if a.border:
        applied.append("border")
    if not applied:
        raise SheetError("no format options given")
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    check_size(rng)
    target = cell_range(sheet, rng)
    for name, value in props_.items():
        target.setPropertyValue(name, value)
    if a.border:
        _apply_border(target, a.border, normalize_color(a.border_color or "000000"))
    return {"sheet": sheet.Name, "range": range_str(rng), "applied": sorted(applied)}


def col_width(doc, a):
    if a.width <= 0:
        raise SheetError("--width must be > 0")
    sheet = doc.sheet(a.sheet)
    col = col_to_idx(a.col)
    sheet.Columns.getByIndex(col - 1).Width = round(a.width * COL_WIDTH_MM100_PER_CHAR)
    return {"sheet": sheet.Name, "col": a.col.upper(), "width": a.width}


def _boundary_cells(rng):
    r1, c1, r2, c2 = rng
    for r in range(r1 - 1, r2):
        for c in range(c1 - 1, c2):
            if r in (r1 - 1, r2 - 1) or c in (c1 - 1, c2 - 1):
                yield r, c


def _all_cells(rng):
    r1, c1, r2, c2 = rng
    return ((r, c) for r in range(r1 - 1, r2) for c in range(c1 - 1, c2))


def _merged_areas(sheet, rng):
    """Distinct multi-cell merged areas (c1, r1, c2, r2, 0-based) touching rng.
    getIsMerged flags only a merge's top-left cell, so partial overlaps are found via the
    boundary cells (any area crossing rng's edge covers one); full scan only if areas lie inside."""
    cells = _all_cells(rng) if cell_range(sheet, rng).getIsMerged() else _boundary_cells(rng)
    areas = set()
    for r, c in cells:
        cursor = sheet.createCursorByRange(sheet.getCellByPosition(c, r))
        cursor.collapseToMergedArea()
        a = cursor.RangeAddress
        if a.EndColumn > a.StartColumn or a.EndRow > a.StartRow:
            areas.add((a.StartColumn, a.StartRow, a.EndColumn, a.EndRow))
    return areas


def merge(doc, a):
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    r1, c1, r2, c2 = rng
    if (r1, c1) == (r2, c2):
        raise SheetError("merge range must span more than one cell")
    if _merged_areas(sheet, rng):
        raise SheetError(f"overlaps existing merge in {range_str(rng)}")
    if c2 > c1:
        cell_range(sheet, (r1, c1 + 1, r1, c2)).clearContents(CONTENT_AND_NOTES)
    if r2 > r1:
        cell_range(sheet, (r1 + 1, c1, r2, c2)).clearContents(CONTENT_AND_NOTES)
    cell_range(sheet, rng).merge(True)
    return {"sheet": sheet.Name, "merged": range_str(rng)}


def unmerge(doc, a):
    sheet = doc.sheet(a.sheet)
    areas = _merged_areas(sheet, parse_range(a.range))
    for c1, r1, c2, r2 in areas:
        cell_range(sheet, (r1 + 1, c1 + 1, r2 + 1, c2 + 1)).merge(False)
    return {"sheet": sheet.Name, "unmerged": len(areas)}


PT_MM100 = 35.28


def row_height(doc, a):
    if a.height <= 0:
        raise SheetError("--height must be > 0")
    sheet = doc.sheet(a.sheet)
    rows, first, last = row_span(sheet, a.rows)
    rows.OptimalHeight = False
    rows.Height = round(a.height * PT_MM100)
    return {"sheet": sheet.Name, "rows": f"{first}:{last}", "height": a.height}


def autofit(doc, a):
    if not (a.cols or a.rows):
        raise SheetError("give --cols and/or --rows")
    sheet = doc.sheet(a.sheet)
    out = {"sheet": sheet.Name}
    if a.cols:
        cols, first, last = col_span(sheet, a.cols)
        cols.OptimalWidth = True
        out["cols"] = f"{first}:{last}"
    if a.rows:
        rows, first, last = row_span(sheet, a.rows)
        rows.OptimalHeight = True
        out["rows"] = f"{first}:{last}"
    return out


def _hex(color):
    return f"{color & 0xFFFFFF:06X}"


def _border(line):
    if line.LineStyle == NO_LINE:
        return None
    return {"color": _hex(line.Color), "width_mm": round(line.LineWidth / 100, 2)}


def _enum_name(value):
    return value.value.lower()


def _merged_range(sheet, cell):
    cursor = sheet.createCursorByRange(cell)
    cursor.collapseToMergedArea()
    a = cursor.RangeAddress
    if a.EndColumn == a.StartColumn and a.EndRow == a.StartRow:
        return False
    return range_str((a.StartRow + 1, a.StartColumn + 1, a.EndRow + 1, a.EndColumn + 1))


def get_format(doc, a):
    sheet = doc.sheet(a.sheet)
    row, col = parse_cell(a.cell)
    cell = sheet.getCellByPosition(col - 1, row - 1)
    fill = None if cell.IsCellBackgroundTransparent else _hex(cell.CellBackColor)
    return {
        "sheet": sheet.Name,
        "cell": cell_ref(row, col),
        "font": {
            "name": cell.CharFontName,
            "size": cell.CharHeight,
            "bold": cell.CharWeight > 100,
            "italic": _enum_name(cell.CharPosture) != "none",
            "underline": cell.CharUnderline != 0,
            "strike": cell.CharStrikeout != 0,
            "color": None if cell.CharColor == -1 else _hex(cell.CharColor),
        },
        "fill": fill,
        "number_format": doc.comp.NumberFormats.getByKey(cell.NumberFormat).FormatString,
        "align": _enum_name(cell.HoriJustify),
        "valign": VERT_NAMES[int(cell.VertJustify)],
        "wrap": bool(cell.IsTextWrapped),
        "borders": {s: _border(getattr(cell, f"{s.capitalize()}Border2"))
                    for s in ("top", "bottom", "left", "right")},
        "merged": _merged_range(sheet, cell),
        "col_width": round(cell.Columns.getByIndex(0).Width / COL_WIDTH_MM100_PER_CHAR, 2),
        "row_height": round(cell.Rows.getByIndex(0).Height / PT_MM100, 2),
    }


OPERATORS = {"gt": "GREATER", "lt": "LESS", "ge": "GREATER_EQUAL", "le": "LESS_EQUAL",
             "eq": "EQUAL", "ne": "NOT_EQUAL", "between": "BETWEEN"}


def _operand(text):
    try:
        float(text)
        return text
    except ValueError:
        return '"' + text.replace('"', '""') + '"'


def _condition(a, top_left):
    """Returns (ConditionOperator name, Formula1, Formula2)."""
    if a.condition == "formula":
        return "FORMULA", a.value.lstrip("="), ""
    if a.condition == "contains":
        needle = a.value.replace('"', '""')
        return "FORMULA", f'ISNUMBER(SEARCH("{needle}";{top_left}))', ""
    if a.condition == "between":
        if a.value2 is None:
            raise SheetError("--value2 required for between")
        return "BETWEEN", _operand(a.value), _operand(a.value2)
    return OPERATORS[a.condition], _operand(a.value), ""


def _cf_style(doc, a):
    styles = doc.comp.StyleFamilies.getByName("CellStyles")
    taken = set(styles.ElementNames)
    name = next(f"sheetcli_cf_{i}" for i in range(1, len(taken) + 2) if f"sheetcli_cf_{i}" not in taken)
    style = doc.comp.createInstance("com.sun.star.style.CellStyle")
    styles.insertByName(name, style)
    if a.fill:
        style.CellBackColor = int(normalize_color(a.fill), 16)
    if a.font_color:
        style.CharColor = int(normalize_color(a.font_color), 16)
    if a.bold:
        style.CharWeight = 150.0
    return name


def cond_format(doc, a):
    import uno
    from com.sun.star.table import CellAddress
    if not (a.fill or a.font_color or a.bold):
        raise SheetError("give at least one of --fill, --font-color, --bold")
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    check_size(rng)
    target = cell_range(sheet, rng)
    top_left = cell_ref(rng[0], rng[1])
    operator, formula1, formula2 = _condition(a, top_left)
    entries = target.ConditionalFormat
    entries.addNew(props(
        Operator=uno.Enum("com.sun.star.sheet.ConditionOperator", operator),
        Formula1=formula1, Formula2=formula2,
        SourcePosition=CellAddress(sheet.RangeAddress.Sheet, rng[1] - 1, rng[0] - 1),
        StyleName=_cf_style(doc, a)))
    target.ConditionalFormat = entries
    return {"sheet": sheet.Name, "range": range_str(rng), "condition": a.condition}


def cond_format_clear(doc, a):
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    target = cell_range(sheet, rng)
    entries = target.ConditionalFormat
    entries.clear()
    target.ConditionalFormat = entries
    return {"sheet": sheet.Name, "range": range_str(rng)}


HANDLERS = {
    "format": Handler(format_, mutates=True, rich=True),
    "col-width": Handler(col_width, mutates=True, rich=True),
    "merge": Handler(merge, mutates=True, rich=True),
    "unmerge": Handler(unmerge, mutates=True, rich=True),
    "row-height": Handler(row_height, mutates=True, rich=True),
    "autofit": Handler(autofit, mutates=True, rich=True),
    "get-format": Handler(get_format, rich=True),
    "cond-format": Handler(cond_format, mutates=True, rich=True),
    "cond-format-clear": Handler(cond_format_clear, mutates=True, rich=True),
}
