import os
import re

MAX_FILE = 50 * 1024 * 1024
MAX_CELLS = 1_000_000
MAX_ROW = 1048576
MAX_COL = 16384


class SheetError(Exception):
    def __init__(self, message, **extra):
        super().__init__(message)
        self.extra = extra


def col_to_idx(letters):
    if not re.fullmatch(r"[A-Za-z]{1,3}", letters or ""):
        raise SheetError(f"bad column: {letters!r}")
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    if n > MAX_COL:
        raise SheetError(f"column out of range: {letters}")
    return n


def idx_to_col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def cell_ref(r, c):
    return f"{idx_to_col(c)}{r}"


def parse_cell(ref):
    m = re.fullmatch(r"\$?([A-Za-z]{1,3})\$?(\d+)", ref or "")
    if not m:
        raise SheetError(f"bad cell reference: {ref!r}")
    r = int(m[2])
    if not 1 <= r <= MAX_ROW:
        raise SheetError(f"row out of range: {ref}")
    return r, col_to_idx(m[1])


def parse_range(ref):
    parts = (ref or "").split(":")
    if len(parts) > 2:
        raise SheetError(f"bad range: {ref!r}")
    r1, c1 = parse_cell(parts[0])
    r2, c2 = parse_cell(parts[-1])
    rng = (min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))
    return rng


def range_str(rng):
    r1, c1, r2, c2 = rng
    return f"{cell_ref(r1, c1)}:{cell_ref(r2, c2)}"


def check_size(rng):
    r1, c1, r2, c2 = rng
    if (r2 - r1 + 1) * (c2 - c1 + 1) > MAX_CELLS:
        raise SheetError(f"range too large (max {MAX_CELLS} cells)")


_INT = re.compile(r"[+-]?(0|[1-9]\d*)")
_FLOAT = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")


def autotype(s):
    if s is None or s == "":
        return None
    if s.startswith("="):
        return s
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if _INT.fullmatch(s):
        return int(s)
    if _FLOAT.fullmatch(s) and not re.fullmatch(r"[+-]?0\d+", s):
        return float(s)
    return s


def normalize_color(s):
    h = (s or "").lstrip("#")
    if len(h) == 8:
        h = h[2:]
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        raise SheetError(f"bad hex color: {s!r}")
    return h.upper()


def check_input_file(path):
    if not os.path.isfile(path):
        raise SheetError(f"file not found: {path}")
    if os.path.getsize(path) > MAX_FILE:
        raise SheetError("file too large (max 50 MB)")


_BAD_NAME = re.compile(r"[\[\]:*?/\\]")


def check_sheet_name(name):
    if not name or len(name) > 31 or _BAD_NAME.search(name):
        raise SheetError(f"invalid sheet name: {name!r} (1-31 chars, none of []:*?/\\)")


FORMATS = ("xlsx", "ods", "csv")


def fmt_of(path):
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext not in FORMATS:
        raise SheetError("unsupported file type")
    return ext


def parse_row_span(span):
    parts = str(span).split(":")
    if len(parts) > 2 or not all(p.isdigit() for p in parts):
        raise SheetError(f"bad row span: {span!r}")
    first, last = int(parts[0]), int(parts[-1])
    if not 1 <= min(first, last) or max(first, last) > MAX_ROW:
        raise SheetError(f"row out of range: {span}")
    return min(first, last), max(first, last)


def parse_col_span(span):
    parts = str(span).split(":")
    if len(parts) > 2:
        raise SheetError(f"bad column span: {span!r}")
    first, last = (int(p) if p.isdigit() else col_to_idx(p) for p in parts[0:1] + parts[-1:])
    return min(first, last), max(first, last)
