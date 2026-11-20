from .common import (SheetError, check_sheet_name, overlaps, parse_range,
                     range_str, shift_rows)


class MemSheet:
    def __init__(self, name):
        self.name = name
        self.cells = {}
        self.styles = {}
        self.merged = []
        self.widths = {}

    @property
    def max_row(self):
        return max((r for r, _ in self.cells), default=0)

    @property
    def max_col(self):
        return max((c for _, c in self.cells), default=0)

    def get(self, r, c):
        return self.cells.get((r, c))

    def set(self, r, c, v):
        if v is None:
            self.cells.pop((r, c), None)
        else:
            self.cells[(r, c)] = v

    def items(self):
        return sorted((r, c, v) for (r, c), v in self.cells.items())

    def _remap(self, at, count):
        def remap(d):
            out = {}
            for (r, c), v in d.items():
                span = shift_rows(r, r, at, count)
                if span:
                    out[(span[0], c)] = v
            return out

        self.cells = remap(self.cells)
        self.styles = remap(self.styles)
        merged = []
        for m in self.merged:
            r1, c1, r2, c2 = parse_range(m)
            span = shift_rows(r1, r2, at, count)
            if span and (span[0], c1) != (span[1], c2):
                merged.append(range_str((span[0], c1, span[1], c2)))
        self.merged = merged

    def insert_rows(self, at, count):
        self._remap(at, count)

    def delete_rows(self, at, count):
        self._remap(at, -count)

    def merges(self):
        return list(self.merged)

    def merge(self, ref):
        r1, c1, r2, c2 = parse_range(ref)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                if (r, c) != (r1, c1):
                    self.cells.pop((r, c), None)
        self.merged.append(range_str((r1, c1, r2, c2)))

    def unmerge(self, ref):
        rng = parse_range(ref)
        self.merged = [m for m in self.merged if not overlaps(parse_range(m), rng)]

    def apply_format(self, r1, c1, r2, c2, fmt):
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                self.styles[(r, c)] = {**self.styles.get((r, c), {}), **fmt}

    def style_items(self):
        return sorted(self.styles.items())

    def set_col_width(self, c, w):
        self.widths[c] = w

    def width_items(self):
        return sorted(self.widths.items())


class Book:
    fmt = ""
    formatting = True
    multi_sheet = True

    def __init__(self):
        self.sheets = []

    def _need(self, flag):
        if not getattr(self, flag):
            raise SheetError(f"unsupported for {self.fmt}")

    def require_formatting(self):
        self._need("formatting")

    def check_format(self, fmt):
        self.require_formatting()

    def names(self):
        return [s.name for s in self.sheets]

    def sheet(self, name=None):
        if name is None:
            return self.sheets[0]
        for s in self.sheets:
            if s.name == name:
                return s
        raise SheetError(f"sheet not found: {name}")

    def _new_sheet(self, name):
        return MemSheet(name)

    def _drop_sheet(self, sheet):
        pass

    def add_sheet(self, name):
        self._need("multi_sheet")
        check_sheet_name(name)
        if name in self.names():
            raise SheetError(f"sheet already exists: {name}")
        self.sheets.append(self._new_sheet(name))

    def remove_sheet(self, name):
        self._need("multi_sheet")
        s = self.sheet(name)
        if len(self.sheets) == 1:
            raise SheetError("cannot delete the only sheet")
        self._drop_sheet(s)
        self.sheets.remove(s)

    def rename_sheet(self, old, new):
        self._need("multi_sheet")
        s = self.sheet(old)
        check_sheet_name(new)
        if new != old and new in self.names():
            raise SheetError(f"sheet already exists: {new}")
        s.name = new
