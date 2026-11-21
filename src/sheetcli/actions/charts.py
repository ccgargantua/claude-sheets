import os

from ..cells import cell_range
from ..common import SheetError, cell_ref, parse_cell, parse_range, range_str
from ..document import file_url, props
from .base import Handler, cmd, with_sheet


def register(sub):
    sp = with_sheet(cmd(sub, "chart"))
    sp.add_argument("--range", required=True)
    sp.add_argument("--type", required=True,
                    choices=["bar", "column", "line", "pie", "scatter", "area"])
    sp.add_argument("--anchor", required=True)
    sp.add_argument("--title")
    sp.add_argument("--name")
    sp.add_argument("--header", action="store_true")
    sp.add_argument("--width-mm", type=float, default=160)
    sp.add_argument("--height-mm", type=float, default=90)
    with_sheet(cmd(sub, "delete-chart")).add_argument("--name", required=True)
    with_sheet(cmd(sub, "charts"))
    sp = with_sheet(cmd(sub, "image"))
    sp.add_argument("--path", required=True)
    sp.add_argument("--anchor", required=True)
    sp.add_argument("--width-mm", type=float)
    sp.add_argument("--height-mm", type=float)


DIAGRAMS = {"bar": "BarDiagram", "column": "BarDiagram", "line": "LineDiagram", "pie": "PieDiagram",
            "scatter": "XYDiagram", "area": "AreaDiagram"}
MAX_IMAGE = 50 * 1024 * 1024
PX_100THMM = 2646
SNAP = 50


def _cell(sheet, ref):
    r, c = parse_cell(ref)
    return sheet.getCellByPosition(c - 1, r - 1)


def _chart_entries(sheet):
    """(public name, chart, OLE shape) per chart. xlsx drops chart names but keeps shape names."""
    page = sheet.DrawPage
    shapes = {}
    for i in range(page.Count):
        shape = page.getByIndex(i)
        if shape.ShapeType.endswith("OLE2Shape"):
            shapes[shape.PersistName] = shape
    for element in sheet.Charts.ElementNames:
        shape = shapes.get(element)
        yield (shape.Name if shape and shape.Name else element), sheet.Charts.getByName(element), shape


def _anchor_of(sheet, shape):
    addr = getattr(shape.Anchor, "CellAddress", None)
    if addr:
        return cell_ref(addr.Row + 1, addr.Column + 1)
    col = row = 0
    x = y = 0
    while x + sheet.Columns.getByIndex(col).Width <= shape.Position.X + SNAP:
        x += sheet.Columns.getByIndex(col).Width
        col += 1
    while y + sheet.Rows.getByIndex(row).Height <= shape.Position.Y + SNAP:
        y += sheet.Rows.getByIndex(row).Height
        row += 1
    return cell_ref(row + 1, col + 1)


def _chart_type(chart):
    diagram = chart.EmbeddedObject.Diagram
    kind = diagram.getDiagramType().rsplit(".", 1)[-1]
    if kind == "BarDiagram":
        return "bar" if diagram.Vertical else "column"
    return {v: k for k, v in DIAGRAMS.items() if k != "column"}.get(kind, kind)


def _chart_info(sheet, name, chart, shape):
    ranges = [range_str((a.StartRow + 1, a.StartColumn + 1, a.EndRow + 1, a.EndColumn + 1))
              for a in chart.Ranges]
    return {"sheet": sheet.Name, "name": name, "type": _chart_type(chart),
            "range": ",".join(ranges), "anchor": _anchor_of(sheet, shape) if shape else None}


def _all_names(doc):
    return {n for s in doc.sheet_names() for n, _, _ in _chart_entries(doc.sheet(s))}


def _auto_name(doc):
    taken = _all_names(doc)
    i = 1
    while f"Chart{i}" in taken:
        i += 1
    return f"Chart{i}"


def chart(doc, a):
    from com.sun.star.awt import Rectangle
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    name = a.name or _auto_name(doc)
    if name in _all_names(doc):
        raise SheetError(f"chart exists: {name}")
    pos = _cell(sheet, a.anchor).Position
    rect = Rectangle(pos.X, pos.Y, int(a.width_mm * 100), int(a.height_mm * 100))
    addr = cell_range(sheet, rng).RangeAddress
    sheet.Charts.addNewByName(name, rect, (addr,), a.header, a.header)
    embedded = sheet.Charts.getByName(name).EmbeddedObject
    next(sh for n, _, sh in _chart_entries(sheet) if n == name).Name = name
    diagram = embedded.createInstance(f"com.sun.star.chart.{DIAGRAMS[a.type]}")
    embedded.setDiagram(diagram)
    if a.type == "bar":
        diagram.Vertical = True
    if a.title:
        embedded.HasMainTitle = True
        embedded.Title.String = a.title
    return {"sheet": sheet.Name, "name": name, "type": a.type, "range": range_str(rng), "anchor": a.anchor.upper()}


def _sheets(doc, name):
    return [doc.sheet(name)] if name else [doc.sheet(n) for n in doc.sheet_names()]


def delete_chart(doc, a):
    for sheet in _sheets(doc, a.sheet):
        for name, chart, shape in _chart_entries(sheet):
            if name == a.name:
                sheet.Charts.removeByName(chart.Name)
                return {"sheet": sheet.Name, "name": name}
    raise SheetError(f"chart not found: {a.name}")


def charts(doc, a):
    out = [_chart_info(s, *entry) for s in _sheets(doc, a.sheet) for entry in _chart_entries(s)]
    return {"count": len(out), "charts": out}


def _natural_size(graphic):
    """(w, h) in 1/100 mm; images without DPI info fall back to 96 dpi."""
    if graphic is None:
        return None
    size = graphic.Size100thMM
    if size.Width and size.Height:
        return size.Width, size.Height
    px = graphic.SizePixel
    if px.Width and px.Height:
        return px.Width * PX_100THMM, px.Height * PX_100THMM
    return None


def image(doc, a):
    from com.sun.star.awt import Point, Size
    if not os.path.isfile(a.path):
        raise SheetError(f"image not found: {a.path}")
    if os.path.getsize(a.path) > MAX_IMAGE:
        raise SheetError("image too large (max 50 MB)")
    sheet = doc.sheet(a.sheet)
    anchor = _cell(sheet, a.anchor)
    shape = doc.comp.createInstance("com.sun.star.drawing.GraphicObjectShape")
    sheet.DrawPage.add(shape)
    try:
        shape.GraphicURL = file_url(a.path)
    except Exception:
        sheet.DrawPage.remove(shape)
        raise SheetError(f"unreadable image: {a.path}")
    natural = _natural_size(shape.Graphic)
    if not natural:
        sheet.DrawPage.remove(shape)
        raise SheetError(f"unreadable image: {a.path}")
    width, height = natural
    if a.width_mm and a.height_mm:
        width, height = int(a.width_mm * 100), int(a.height_mm * 100)
    elif a.width_mm:
        width, height = int(a.width_mm * 100), int(a.width_mm * 100 * natural[1] / natural[0])
    elif a.height_mm:
        width, height = int(a.height_mm * 100 * natural[0] / natural[1]), int(a.height_mm * 100)
    shape.Anchor = anchor
    shape.Position = Point(anchor.Position.X, anchor.Position.Y)
    shape.Size = Size(width, height)
    return {"sheet": sheet.Name, "anchor": a.anchor.upper(), "width_mm": width / 100, "height_mm": height / 100}


HANDLERS = {
    "chart": Handler(chart, mutates=True, rich=True),
    "delete-chart": Handler(delete_chart, mutates=True, rich=True),
    "charts": Handler(charts, rich=True),
    "image": Handler(image, mutates=True, rich=True),
}
