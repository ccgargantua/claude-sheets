import re
from datetime import date

from ..cells import cell_range
from ..common import SheetError, idx_to_col, parse_cell, parse_range, range_str
from .base import Handler, cmd, with_sheet


def register(sub):
    sp = with_sheet(cmd(sub, "define-name"))
    sp.add_argument("--name", required=True)
    sp.add_argument("--range", required=True)
    cmd(sub, "delete-name").add_argument("--name", required=True)
    cmd(sub, "names")
    sp = with_sheet(cmd(sub, "validation"))
    sp.add_argument("--range", required=True)
    sp.add_argument("--type", required=True,
                    choices=["list", "whole", "decimal", "date", "text-length"])
    sp.add_argument("--values")
    sp.add_argument("--min")
    sp.add_argument("--max")
    with_sheet(cmd(sub, "validation-clear")).add_argument("--range", required=True)
    sp = with_sheet(cmd(sub, "comment"))
    sp.add_argument("--cell", required=True)
    sp.add_argument("--text", required=True)
    with_sheet(cmd(sub, "delete-comment")).add_argument("--cell", required=True)
    sp = with_sheet(cmd(sub, "hyperlink"))
    sp.add_argument("--cell", required=True)
    sp.add_argument("--url", required=True)
    sp.add_argument("--text")
    for name in ("protect", "unprotect"):
        sp = with_sheet(cmd(sub, name))
        sp.add_argument("--password")


def _qualified(doc, a):
    """(sheet object, range) from --range, honoring 'Sheet2!A1:B3' / "'My Sheet'!A1"."""
    text = a.range
    if "!" in text:
        name, text = text.rsplit("!", 1)
        if len(name) > 1 and name[0] == name[-1] == "'":
            name = name[1:-1].replace("''", "'")
        return doc.sheet(name), parse_range(text)
    return doc.sheet(a.sheet), parse_range(text)


def _content(sheet, rng):
    r1, c1, r2, c2 = rng
    name = sheet.Name.replace("'", "''")
    corner = lambda r, c: f"${idx_to_col(c)}${r}"
    tail = corner(r1, c1) if (r1, c1) == (r2, c2) else f"{corner(r1, c1)}:{corner(r2, c2)}"
    return f"$'{name}'.{tail}"


def _public_range(content):
    m = re.fullmatch(r"\$?'?([^'.]+(?:''[^'.]*)*)'?\.\$?([A-Z]+)\$?(\d+)(?::\$?([A-Z]+)\$?(\d+))?", content)
    if not m:
        return content
    sheet, c1, r1, c2, r2 = m.groups()
    ref = f"{c1}{r1}" + (f":{c2}{r2}" if c2 else "")
    return f"{sheet}!{ref}"


def define_name(doc, a):
    from com.sun.star.table import CellAddress
    if not a.name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", a.name):
        raise SheetError(f"invalid name: {a.name!r}")
    names = doc.comp.NamedRanges
    if names.hasByName(a.name):
        raise SheetError(f"name exists: {a.name}")
    sheet, rng = _qualified(doc, a)
    names.addNewByName(a.name, _content(sheet, rng), CellAddress(), 0)
    return {"name": a.name, "range": f"{sheet.Name}!{range_str(rng)}"}


def delete_name(doc, a):
    names = doc.comp.NamedRanges
    if not names.hasByName(a.name):
        raise SheetError(f"name not found: {a.name}")
    names.removeByName(a.name)
    return {"name": a.name}


def names(doc, a):
    named = doc.comp.NamedRanges
    out = [{"name": n, "range": _public_range(named.getByName(n).Content)} for n in named.ElementNames]
    return {"count": len(out), "names": out}


def _serial(doc, text):
    nd = doc.comp.NullDate
    try:
        return str((date.fromisoformat(text) - date(nd.Year, nd.Month, nd.Day)).days)
    except ValueError:
        raise SheetError(f"bad date (use YYYY-MM-DD): {text!r}")


def _number(text, kind):
    try:
        return str(int(text)) if kind in ("whole", "text-length") else str(float(text))
    except ValueError:
        raise SheetError(f"bad {kind} bound: {text!r}")


def validation(doc, a):
    from com.sun.star.sheet.ValidationType import DATE, DECIMAL, LIST, TEXT_LEN, WHOLE
    from com.sun.star.sheet.ConditionOperator import BETWEEN, GREATER_EQUAL, LESS_EQUAL
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    val = cell_range(sheet, rng).Validation
    if a.type == "list":
        items = [v.strip() for v in (a.values or "").split(",") if v.strip()]
        if not items:
            raise SheetError("--values required for list")
        val.Type = LIST
        val.Formula1 = ";".join('"' + v.replace('"', '""') + '"' for v in items)
        val.ShowList = 1
        val.Operator = BETWEEN
    else:
        if a.min is None and a.max is None:
            raise SheetError("--min and/or --max required")
        conv = (lambda t: _serial(doc, t)) if a.type == "date" else (lambda t: _number(t, a.type))
        lo, hi = (conv(v) if v is not None else None for v in (a.min, a.max))
        val.Type = {"whole": WHOLE, "decimal": DECIMAL, "date": DATE, "text-length": TEXT_LEN}[a.type]
        if lo is not None and hi is not None:
            val.Operator, val.Formula1, val.Formula2 = BETWEEN, lo, hi
        elif lo is not None:
            val.Operator, val.Formula1 = GREATER_EQUAL, lo
        else:
            val.Operator, val.Formula1 = LESS_EQUAL, hi
    val.ShowErrorMessage = True
    cell_range(sheet, rng).Validation = val
    return {"sheet": sheet.Name, "range": range_str(rng), "type": a.type}


def validation_clear(doc, a):
    from com.sun.star.sheet.ValidationType import ANY
    sheet = doc.sheet(a.sheet)
    rng = parse_range(a.range)
    target = cell_range(sheet, rng)
    val = target.Validation
    val.Type = ANY
    val.ShowErrorMessage = False
    target.Validation = val
    return {"sheet": sheet.Name, "range": range_str(rng)}


def _address(sheet, ref):
    r, c = parse_cell(ref)
    return sheet.getCellByPosition(c - 1, r - 1).CellAddress


def _comment_index(sheet, addr):
    notes = sheet.Annotations
    for i in range(notes.Count):
        p = notes.getByIndex(i).Position
        if (p.Column, p.Row) == (addr.Column, addr.Row):
            return i
    return None


def comment(doc, a):
    sheet = doc.sheet(a.sheet)
    addr = _address(sheet, a.cell)
    i = _comment_index(sheet, addr)
    if i is not None:
        sheet.Annotations.removeByIndex(i)
    sheet.Annotations.insertNew(addr, a.text)
    return {"sheet": sheet.Name, "cell": a.cell.upper()}


def delete_comment(doc, a):
    sheet = doc.sheet(a.sheet)
    i = _comment_index(sheet, _address(sheet, a.cell))
    if i is None:
        raise SheetError(f"no comment at {a.cell}")
    sheet.Annotations.removeByIndex(i)
    return {"sheet": sheet.Name, "cell": a.cell.upper()}


def hyperlink(doc, a):
    sheet = doc.sheet(a.sheet)
    r, c = parse_cell(a.cell)
    cell = sheet.getCellByPosition(c - 1, r - 1)
    field = doc.comp.createInstance("com.sun.star.text.TextField.URL")
    field.URL, field.Representation = a.url, a.text or a.url
    cell.setString("")
    cell.Text.insertTextContent(cell.Text.createTextCursor(), field, False)
    return {"sheet": sheet.Name, "cell": a.cell.upper(), "url": a.url}


def protect(doc, a):
    sheet = doc.sheet(a.sheet)
    if sheet.isProtected():
        raise SheetError(f"already protected: {sheet.Name}")
    sheet.protect(a.password or "")
    return {"sheet": sheet.Name, "protected": True}


def unprotect(doc, a):
    sheet = doc.sheet(a.sheet)
    if not sheet.isProtected():
        raise SheetError(f"not protected: {sheet.Name}")
    try:
        sheet.unprotect(a.password or "")
    except Exception:
        raise SheetError("wrong password")
    return {"sheet": sheet.Name, "protected": False}



HANDLERS = {
    "define-name": Handler(define_name, mutates=True, rich=True),
    "delete-name": Handler(delete_name, mutates=True, rich=True),
    "names": Handler(names, rich=True),
    "validation": Handler(validation, mutates=True, rich=True),
    "validation-clear": Handler(validation_clear, mutates=True, rich=True),
    "comment": Handler(comment, mutates=True, rich=True),
    "delete-comment": Handler(delete_comment, mutates=True, rich=True),
    "hyperlink": Handler(hyperlink, mutates=True, rich=True),
    "protect": Handler(protect, mutates=True, rich=True),
    "unprotect": Handler(unprotect, mutates=True, rich=True),
}
