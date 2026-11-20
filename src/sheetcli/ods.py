import re
import zipfile

from odf import number, style, teletype, text
from odf.namespaces import FONS, NUMBERNS, OFFICENS, STYLENS, TABLENS
from odf.opendocument import OpenDocumentSpreadsheet, load
from odf.table import CoveredTableCell, Table, TableCell, TableColumn, TableRow
from odf.text import P

from .common import MAX_CELLS, SheetError, check_zip, parse_range, range_str
from .model import Book, MemSheet

CM_PER_CHAR = 0.185
_NUMFMT = re.compile(r"(#,##)?0(\.(0+))?(%)?")
_UNIT_CM = {"cm": 1.0, "mm": 0.1, "in": 2.54, "pt": 2.54 / 72, "pc": 2.54 / 6}
_REF = re.compile(r"(?<![A-Za-z0-9_.!$])(\$?[A-Z]{1,3}\$?\d+)(?::(\$?[A-Z]{1,3}\$?\d+))?(?![A-Za-z0-9_(])")
_ODS_REF = re.compile(r"\[\.([^\]:]+)(?::\.([^\]]+))?\]")
_STR = re.compile(r'("(?:[^"]|"")*")')


def parse_numfmt(s):
    m = _NUMFMT.fullmatch(s)
    if not m:
        raise SheetError(
            f"number format not supported in ods: {s!r} "
            "(supported: General, 0, 0.00, #,##0, #,##0.00, 0%, 0.00%, ...)")
    return len(m[3] or ""), bool(m[1]), bool(m[4])


def _split_strings(f, fn):
    parts = _STR.split(f)
    return "".join(p if i % 2 else fn(p) for i, p in enumerate(parts))


def to_ods_formula(f):
    def conv(p):
        p = _REF.sub(lambda m: "[." + m[1] + (":." + m[2] if m[2] else "") + "]", p)
        return p.replace(",", ";")

    return "of:=" + _split_strings(f[1:], conv)


def from_ods_formula(f):
    body = f.partition(":=")[2] if ":=" in f else f.lstrip("=")

    def conv(p):
        p = _ODS_REF.sub(lambda m: m[1] + (":" + m[2] if m[2] else ""), p)
        return p.replace(";", ",")

    return "=" + _split_strings(body, conv)


def _to_cm(s):
    m = re.fullmatch(r"([\d.]+)\s*([a-z]+)", s or "")
    return float(m[1]) * _UNIT_CM[m[2]] if m and m[2] in _UNIT_CM else None


def _attr(node, ns, name):
    return node.getAttrNS(ns, name)


def _int_attr(node, ns, name):
    v = _attr(node, ns, name)
    return int(v) if v else 1


def _num_patterns(doc):
    out = {}
    for tag in (number.NumberStyle, number.PercentageStyle):
        for ns in doc.getElementsByType(tag):
            n = ns.getElementsByType(number.Number)
            if not n:
                continue
            dec = int(_attr(n[0], NUMBERNS, "decimal-places") or 0)
            pat = ("#,##" if _attr(n[0], NUMBERNS, "grouping") == "true" else "") + "0"
            pat += "." + "0" * dec if dec else ""
            if tag is number.PercentageStyle:
                pat += "%"
            out[_attr(ns, STYLENS, "name")] = pat
    return out


def _read_cell_styles(doc):
    patterns = _num_patterns(doc)
    raw = {}
    for st in doc.getElementsByType(style.Style):
        raw[_attr(st, STYLENS, "name")] = st
    memo = {}

    def resolve(name):
        if name in memo:
            return memo[name]
        st = raw.get(name)
        fmt = {}
        memo[name] = fmt
        if st is None or _attr(st, STYLENS, "family") != "table-cell":
            return fmt
        parent = _attr(st, STYLENS, "parent-style-name")
        if parent:
            fmt.update(resolve(parent))
        for tp in st.getElementsByType(style.TextProperties):
            if _attr(tp, FONS, "font-weight") == "bold":
                fmt["bold"] = True
            if _attr(tp, FONS, "font-style") == "italic":
                fmt["italic"] = True
            u = _attr(tp, STYLENS, "text-underline-style")
            if u and u != "none":
                fmt["underline"] = True
            fs = _attr(tp, FONS, "font-size")
            if fs and fs.endswith("pt"):
                fmt["font_size"] = int(float(fs[:-2]))
            col = _attr(tp, FONS, "color")
            if col and re.fullmatch(r"#[0-9a-fA-F]{6}", col):
                fmt["font_color"] = col[1:].upper()
        for cp in st.getElementsByType(style.TableCellProperties):
            bg = _attr(cp, FONS, "background-color")
            if bg and re.fullmatch(r"#[0-9a-fA-F]{6}", bg):
                fmt["fill"] = bg[1:].upper()
        for pp in st.getElementsByType(style.ParagraphProperties):
            a = {"left": "left", "start": "left", "center": "center",
                 "right": "right", "end": "right"}.get(_attr(pp, FONS, "text-align"))
            if a:
                fmt["align"] = a
        ds = _attr(st, STYLENS, "data-style-name")
        if ds in patterns:
            fmt["number_format"] = patterns[ds]
        return fmt

    return resolve


def _read_value(cell):
    formula = _attr(cell, TABLENS, "formula")
    if formula:
        return from_ods_formula(formula)
    vt = _attr(cell, OFFICENS, "value-type")
    if vt in ("float", "percentage", "currency"):
        v = float(_attr(cell, OFFICENS, "value"))
        return int(v) if v.is_integer() else v
    if vt == "boolean":
        return _attr(cell, OFFICENS, "boolean-value") == "true"
    if vt == "date":
        return _attr(cell, OFFICENS, "date-value")
    if vt == "time":
        return _attr(cell, OFFICENS, "time-value")
    ps = [teletype.extractText(p) for p in cell.getElementsByType(text.P)]
    return "\n".join(ps) if ps else None


def _read_sheet(tbl, resolve_style):
    sheet = MemSheet(_attr(tbl, TABLENS, "name"))
    stylemap = {}
    for st in tbl.ownerDocument.automaticstyles.getElementsByType(style.Style):
        if _attr(st, STYLENS, "family") == "table-column":
            props = st.getElementsByType(style.TableColumnProperties)
            if props:
                stylemap[_attr(st, STYLENS, "name")] = _to_cm(_attr(props[0], STYLENS, "column-width"))
    c = 1
    for col in tbl.getElementsByType(TableColumn):
        rep = _int_attr(col, TABLENS, "number-columns-repeated")
        cm = stylemap.get(_attr(col, TABLENS, "style-name"))
        if cm and rep <= 1024:
            for k in range(c, c + rep):
                sheet.widths[k] = round(cm / CM_PER_CHAR, 2)
        c += rep
    r = 1
    total = 0
    for row in tbl.getElementsByType(TableRow):
        rrep = _int_attr(row, TABLENS, "number-rows-repeated")
        c = 1
        entries = []
        for node in row.childNodes:
            if node.qname not in ((TABLENS, "table-cell"), (TABLENS, "covered-table-cell")):
                continue
            crep = _int_attr(node, TABLENS, "number-columns-repeated")
            if node.qname[1] == "table-cell":
                v = _read_value(node)
                fmt = resolve_style(_attr(node, TABLENS, "style-name")) if _attr(node, TABLENS, "style-name") else {}
                cs = _int_attr(node, TABLENS, "number-columns-spanned")
                rs = _int_attr(node, TABLENS, "number-rows-spanned")
                if v is not None or (fmt and crep * rrep <= 10000) or cs > 1 or rs > 1:
                    entries.append((c, min(crep, 1024 if v is None else crep), v, fmt, cs, rs))
            c += crep
        if entries:
            total += rrep * len(entries)
            if total > MAX_CELLS:
                raise SheetError("ods sheet too large")
            for k in range(rrep):
                for cc, crep, v, fmt, cs, rs in entries:
                    for j in range(crep):
                        if v is not None:
                            sheet.cells[(r + k, cc + j)] = v
                        if fmt:
                            sheet.styles[(r + k, cc + j)] = dict(fmt)
                    if k == 0 and (cs > 1 or rs > 1):
                        sheet.merged.append(range_str((r, cc, r + rs - 1, cc + cs - 1)))
        r += rrep
    return sheet


class OdsBook(Book):
    fmt = "ods"

    def __init__(self, sheets):
        super().__init__()
        self.sheets = sheets

    @classmethod
    def new(cls, names):
        return cls([MemSheet(n) for n in names])

    @classmethod
    def load(cls, path):
        check_zip(path)
        try:
            import defusedxml.ElementTree as DET

            with zipfile.ZipFile(path) as z:
                for part in ("content.xml", "styles.xml"):
                    if part in z.namelist():
                        DET.fromstring(z.read(part))
            doc = load(path)
            resolve = _read_cell_styles(doc)
            tables = doc.spreadsheet.getElementsByType(Table)
            sheets = [_read_sheet(t, resolve) for t in tables]
        except SheetError:
            raise
        except Exception as e:
            raise SheetError(f"cannot read ods: {type(e).__name__}: {e}")
        if not sheets:
            raise SheetError("ods file has no sheets")
        return cls(sheets)

    def check_format(self, fmt):
        if "number_format" in fmt and fmt["number_format"].lower() != "general":
            parse_numfmt(fmt["number_format"])

    def save(self, path):
        _Writer().write(self.sheets, path)


class _Writer:
    def __init__(self):
        self.doc = OpenDocumentSpreadsheet()
        self.cell_styles = {}
        self.num_styles = {}
        self.col_styles = {}

    def _num_style(self, pattern):
        if pattern in self.num_styles:
            return self.num_styles[pattern]
        dec, grouping, pct = parse_numfmt(pattern)
        name = f"N{len(self.num_styles) + 1}"
        cls = number.PercentageStyle if pct else number.NumberStyle
        ns = cls(name=name)
        kw = {"decimalplaces": dec, "minintegerdigits": 1}
        if grouping:
            kw["grouping"] = "true"
        ns.addElement(number.Number(**kw))
        if pct:
            ns.addElement(number.Text(text="%"))
        self.doc.automaticstyles.addElement(ns)
        self.num_styles[pattern] = name
        return name

    def _cell_style(self, fmt):
        fmt = {k: v for k, v in fmt.items()
               if not (k == "number_format" and not _supported(v))}
        if not fmt:
            return None
        key = tuple(sorted(fmt.items()))
        if key in self.cell_styles:
            return self.cell_styles[key]
        name = f"ce{len(self.cell_styles) + 1}"
        kw = {}
        if "number_format" in fmt:
            kw["datastylename"] = self._num_style(fmt["number_format"])
        st = style.Style(name=name, family="table-cell", **kw)
        tp = {}
        if fmt.get("bold"):
            tp["fontweight"] = "bold"
        if fmt.get("italic"):
            tp["fontstyle"] = "italic"
        if fmt.get("underline"):
            tp.update(textunderlinestyle="solid", textunderlinewidth="auto",
                      textunderlinecolor="font-color")
        if "font_size" in fmt:
            tp["fontsize"] = f"{fmt['font_size']}pt"
        if "font_color" in fmt:
            tp["color"] = "#" + fmt["font_color"].lower()
        if tp:
            st.addElement(style.TextProperties(**tp))
        if "fill" in fmt:
            st.addElement(style.TableCellProperties(backgroundcolor="#" + fmt["fill"].lower()))
        if "align" in fmt:
            st.addElement(style.ParagraphProperties(textalign=fmt["align"]))
        self.doc.automaticstyles.addElement(st)
        self.cell_styles[key] = name
        return name

    def _col_style(self, width):
        if width not in self.col_styles:
            name = f"co{len(self.col_styles) + 1}"
            st = style.Style(name=name, family="table-column")
            st.addElement(style.TableColumnProperties(columnwidth=f"{width * CM_PER_CHAR:.3f}cm"))
            self.doc.automaticstyles.addElement(st)
            self.col_styles[width] = name
        return self.col_styles[width]

    def _cell(self, v, fmt, span):
        kw = {}
        sname = self._cell_style(fmt) if fmt else None
        if sname:
            kw["stylename"] = sname
        if span:
            kw["numbercolumnsspanned"], kw["numberrowsspanned"] = span
        pct = fmt.get("number_format", "").endswith("%") and _supported(fmt["number_format"])
        if v is None:
            return TableCell(**kw)
        if isinstance(v, bool):
            cell = TableCell(valuetype="boolean", booleanvalue="true" if v else "false", **kw)
            disp = "TRUE" if v else "FALSE"
        elif isinstance(v, (int, float)):
            cell = TableCell(valuetype="percentage" if pct else "float", value=repr(v), **kw)
            disp = str(v)
        elif isinstance(v, str) and v.startswith("="):
            return TableCell(formula=to_ods_formula(v), **kw)
        else:
            cell = TableCell(valuetype="string", **kw)
            disp = str(v)
        p = P()
        teletype.addTextToElement(p, disp)
        cell.addElement(p)
        return cell

    def _table(self, s):
        tbl = Table(name=s.name)
        merges = [parse_range(m) for m in s.merged]
        origin = {(m[0], m[1]): (m[3] - m[1] + 1, m[2] - m[0] + 1) for m in merges}
        covered = {(r, c) for m in merges for r in range(m[0], m[2] + 1)
                   for c in range(m[1], m[3] + 1)} - set(origin)
        widths = dict(s.width_items())
        ncols = max([s.max_col, *widths, *(m[3] for m in merges)], default=1) or 1
        c = 1
        while c <= ncols:
            w = widths.get(c)
            e = c
            while e + 1 <= ncols and widths.get(e + 1) == w:
                e += 1
            kw = {"stylename": self._col_style(w)} if w else {}
            if e > c:
                kw["numbercolumnsrepeated"] = e - c + 1
            tbl.addElement(TableColumn(**kw))
            c = e + 1
        positions = set(s.cells) | set(s.styles) | set(origin) | covered
        by_row = {}
        for r, c in positions:
            by_row.setdefault(r, []).append(c)
        prev = 0
        for r in sorted(by_row):
            if r - prev > 1:
                self._gap_row(tbl, r - prev - 1)
            row = TableRow()
            col = 0
            for c in sorted(by_row[r]):
                if c - col > 1:
                    row.addElement(TableCell(numbercolumnsrepeated=c - col - 1))
                if (r, c) in covered:
                    row.addElement(CoveredTableCell())
                else:
                    row.addElement(self._cell(s.cells.get((r, c)), s.styles.get((r, c), {}), origin.get((r, c))))
                col = c
            tbl.addElement(row)
            prev = r
        if not by_row:
            self._gap_row(tbl, 1)
        return tbl

    @staticmethod
    def _gap_row(tbl, n):
        kw = {"numberrowsrepeated": n} if n > 1 else {}
        row = TableRow(**kw)
        row.addElement(TableCell())
        tbl.addElement(row)

    def write(self, sheets, path):
        for s in sheets:
            self.doc.spreadsheet.addElement(self._table(s))
        self.doc.save(path)


def _supported(pattern):
    try:
        return pattern.lower() != "general" and bool(parse_numfmt(pattern))
    except SheetError:
        return False
