import datetime
from copy import copy

import openpyxl
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Color, PatternFill

from .common import (SheetError, check_zip, idx_to_col, overlaps, parse_range,
                     range_str, shift_rows, col_to_idx)
from .model import Book


def _plain(v):
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    return v


class XlsxSheet:
    def __init__(self, ws):
        self.ws = ws

    @property
    def name(self):
        return self.ws.title

    @name.setter
    def name(self, v):
        self.ws.title = v

    @property
    def max_row(self):
        ws = self.ws
        if ws.max_row == 1 and ws.max_column == 1 and ws["A1"].value is None:
            return 0
        return ws.max_row

    @property
    def max_col(self):
        return self.ws.max_column if self.max_row else 0

    def get(self, r, c):
        return _plain(self.ws.cell(r, c).value)

    def set(self, r, c, v):
        self.ws.cell(r, c).value = v

    def items(self):
        for r, row in enumerate(self.ws.iter_rows(values_only=True), 1):
            for c, v in enumerate(row, 1):
                if v is not None:
                    yield r, c, _plain(v)

    def _reshape(self, op):
        ranges = [parse_range(str(m)) for m in self.ws.merged_cells.ranges]
        for m in ranges:
            self.ws.unmerge_cells(range_str(m))
        op()
        return ranges

    def _shift(self, at, count):
        def op():
            if count > 0:
                self.ws.insert_rows(at, count)
            else:
                self.ws.delete_rows(at, -count)

        for r1, c1, r2, c2 in self._reshape(op):
            span = shift_rows(r1, r2, at, count)
            if span and (span[0], c1) != (span[1], c2):
                self.ws.merge_cells(range_str((span[0], c1, span[1], c2)))

    def insert_rows(self, at, count):
        self._shift(at, count)

    def delete_rows(self, at, count):
        self._shift(at, -count)

    def merges(self):
        return [str(m) for m in self.ws.merged_cells.ranges]

    def merge(self, ref):
        self.ws.merge_cells(ref)

    def unmerge(self, ref):
        rng = parse_range(ref)
        for m in list(self.ws.merged_cells.ranges):
            if overlaps(parse_range(str(m)), rng):
                self.ws.unmerge_cells(str(m))

    def apply_format(self, r1, c1, r2, c2, fmt):
        for row in self.ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2):
            for cell in row:
                if not isinstance(cell, MergedCell):
                    _style_cell(cell, fmt)

    def style_items(self):
        for row in self.ws.iter_rows():
            for cell in row:
                if getattr(cell, "has_style", False):
                    fmt = _read_style(cell)
                    if fmt:
                        yield (cell.row, cell.column), fmt

    def set_col_width(self, c, w):
        self.ws.column_dimensions[idx_to_col(c)].width = w

    def width_items(self):
        out = {}
        for letter, dim in self.ws.column_dimensions.items():
            if dim.width and dim.customWidth:
                lo = dim.min or col_to_idx(letter)
                hi = min(dim.max or lo, lo + 1023)
                for c in range(lo, hi + 1):
                    out[c] = dim.width
        return sorted(out.items())


def _style_cell(cell, fmt):
    if {"bold", "italic", "underline", "font_size", "font_color"} & fmt.keys():
        f = copy(cell.font)
        if "bold" in fmt:
            f.b = True
        if "italic" in fmt:
            f.i = True
        if "underline" in fmt:
            f.u = "single"
        if "font_size" in fmt:
            f.sz = fmt["font_size"]
        if "font_color" in fmt:
            f.color = Color(rgb="FF" + fmt["font_color"])
        cell.font = f
    if "fill" in fmt:
        c = "FF" + fmt["fill"]
        cell.fill = PatternFill(fill_type="solid", start_color=c, end_color=c)
    if "number_format" in fmt:
        cell.number_format = fmt["number_format"]
    if "align" in fmt:
        a = copy(cell.alignment)
        a.horizontal = fmt["align"]
        cell.alignment = a


def _rgb(color):
    rgb = getattr(color, "rgb", None)
    return rgb[-6:] if isinstance(rgb, str) and len(rgb) == 8 else None


def _read_style(cell):
    fmt = {}
    f = cell.font
    if f.b:
        fmt["bold"] = True
    if f.i:
        fmt["italic"] = True
    if f.u:
        fmt["underline"] = True
    if f.sz and f.sz != 11:
        fmt["font_size"] = int(f.sz)
    fc = _rgb(f.color)
    if fc and fc != "000000":
        fmt["font_color"] = fc
    if cell.fill.fill_type == "solid":
        fill = _rgb(cell.fill.fgColor)
        if fill:
            fmt["fill"] = fill
    if cell.number_format != "General":
        fmt["number_format"] = cell.number_format
    if cell.alignment.horizontal in ("left", "center", "right"):
        fmt["align"] = cell.alignment.horizontal
    return fmt


class XlsxBook(Book):
    fmt = "xlsx"

    def __init__(self, wb):
        super().__init__()
        self.wb = wb
        self.sheets = [XlsxSheet(ws) for ws in wb.worksheets]

    @classmethod
    def load(cls, path):
        check_zip(path)
        try:
            return cls(openpyxl.load_workbook(path))
        except SheetError:
            raise
        except Exception as e:
            raise SheetError(f"cannot read xlsx: {type(e).__name__}: {e}")

    @classmethod
    def new(cls, names):
        wb = openpyxl.Workbook()
        wb.active.title = names[0]
        for n in names[1:]:
            wb.create_sheet(n)
        return cls(wb)

    def _new_sheet(self, name):
        return XlsxSheet(self.wb.create_sheet(name))

    def _drop_sheet(self, sheet):
        self.wb.remove(sheet.ws)

    def save(self, path):
        self.wb.save(path)
