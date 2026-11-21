import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone

from .common import MAX_FILE, SheetError, check_sheet_name, fmt_of

FILTERS = {
    "xlsx": "Calc MS Excel 2007 XML",
    "ods": "calc8",
    "csv": "Text - txt - csv (StarCalc)",
}
CSV_LOAD_OPTIONS = "44,34,76,1"
CSV_SAVE_OPTIONS = "44,34,76,1,,0,false"
CSV_SHEET = "Sheet1"
LOCALE = ("en", "US", "")


def props(**kv):
    from com.sun.star.beans import PropertyValue
    return tuple(PropertyValue(k, 0, v, 0) for k, v in kv.items())


def store_props(fmt):
    p = {"FilterName": FILTERS[fmt]}
    if fmt == "csv":
        p["FilterOptions"] = CSV_SAVE_OPTIONS
    return props(**p)


def load_props(fmt):
    p = {"Hidden": True, "FilterName": FILTERS[fmt]}
    if fmt == "csv":
        p["FilterOptions"] = CSV_LOAD_OPTIONS
    return props(**p)


def file_url(path):
    import uno
    return uno.systemPathToFileUrl(os.path.abspath(path))


def check_input_file(path):
    if not os.path.isfile(path):
        raise SheetError(f"file not found: {path}")
    if os.path.getsize(path) > MAX_FILE:
        raise SheetError("file too large (max 50 MB)")


class Doc:
    """Owner: the open_doc/new_doc context that created it; closed on exit."""

    def __init__(self, comp, path, fmt):
        self.comp, self.path, self.fmt = comp, path, fmt
        self._parser = None

    @property
    def sheets(self):
        return self.comp.Sheets

    def sheet_names(self):
        return list(self.sheets.ElementNames)

    def sheet(self, name=None):
        if name is None:
            return self.sheets.getByIndex(0)
        if not self.sheets.hasByName(name):
            raise SheetError(f"sheet not found: {name}")
        return self.sheets.getByName(name)

    def number_format(self, code):
        from com.sun.star.lang import Locale
        formats, loc = self.comp.NumberFormats, Locale(*LOCALE)
        key = formats.queryKey(code, loc, False)
        if key != -1:
            return key
        try:
            return formats.addNew(code, loc)
        except Exception:
            raise SheetError(f"invalid number format: {code!r}")

    def number_format_type(self, key):
        return self.comp.NumberFormats.getByKey(key).Type

    def formula_parser(self):
        if self._parser is None:
            import uno
            from com.sun.star.sheet import FormulaLanguage, FormulaMapGroup as G
            mapper = self.comp.createInstance("com.sun.star.sheet.FormulaOpCodeMapper")
            groups = (G.SPECIAL | G.SEPARATORS | G.ARRAY_SEPARATORS | G.UNARY_OPERATORS
                      | G.BINARY_OPERATORS | G.FUNCTIONS)
            parser = self.comp.createInstance("com.sun.star.sheet.FormulaParser")
            parser.FormulaConvention = uno.getConstantByName("com.sun.star.sheet.AddressConvention.XL_A1")
            parser.CompileEnglish = True
            parser.OpCodeMap = mapper.getAvailableMappings(FormulaLanguage.XL_ENGLISH, groups)
            self._parser = parser
        return self._parser

    def set_formula(self, cell, text):
        from com.sun.star.table import CellAddress
        pos = CellAddress()
        pos.Sheet, pos.Column, pos.Row = (cell.CellAddress.Sheet, cell.CellAddress.Column,
                                          cell.CellAddress.Row)
        cell.setTokens(self.formula_parser().parseFormula(text[1:], pos))

    def formula_text(self, cell):
        return "=" + self.formula_parser().printFormula(cell.getTokens(), cell.CellAddress)

    def recalc(self):
        self.comp.calculateAll()

    def save(self):
        store(self.comp, self.path, self.fmt)


def store(comp, path, fmt):
    directory, base = os.path.split(os.path.abspath(path))
    tmp = os.path.join(directory, f".{base}.sheetcli-{os.getpid()}.tmp")
    try:
        comp.storeToURL(file_url(tmp), store_props(fmt))
        if os.path.exists(path):
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def backup_file(path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = f"{path}.bak-{stamp}"
    shutil.copy2(path, dst)
    return dst


def give_view_area(comp):
    """Hidden docs get a 0x0 window, which makes Calc drop freeze panes on load/export;
    a sized, shown window keeps them. Returns the view controller."""
    controller = comp.getCurrentController()
    if controller is None:
        raise SheetError("document has no view")
    window = controller.getFrame().getContainerWindow()
    window.setVisible(True)
    window.setPosSize(0, 0, 1600, 900, 15)
    return controller


def _remove_lock_file(path):
    if path is None:
        return
    directory, base = os.path.split(os.path.abspath(path))
    try:
        os.remove(os.path.join(directory, f".~lock.{base}#"))
    except OSError:
        pass


def _close(comp, path):
    try:
        comp.close(True)
    except Exception:
        try:
            comp.dispose()
        except Exception:
            pass
    _remove_lock_file(path)


@contextmanager
def open_doc(desktop, path):
    fmt = fmt_of(path)
    check_input_file(path)
    comp = desktop.loadComponentFromURL(file_url(path), "_blank", 0, load_props(fmt))
    if comp is None:
        raise SheetError(f"cannot read {fmt}: {path}")
    try:
        if fmt == "csv":
            comp.Sheets.getByIndex(0).Name = CSV_SHEET
        else:
            give_view_area(comp)
        yield Doc(comp, path, fmt)
    finally:
        _close(comp, path)


def check_new_sheets(path, sheet_names):
    fmt = fmt_of(path)
    for name in sheet_names:
        check_sheet_name(name)
    if len({n.lower() for n in sheet_names}) != len(sheet_names):
        raise SheetError("duplicate sheet names")
    if fmt == "csv" and len(sheet_names) > 1:
        raise SheetError("unsupported for csv")


@contextmanager
def new_doc(desktop, path, sheet_names):
    comp = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, props(Hidden=True))
    try:
        comp.Sheets.getByIndex(0).Name = sheet_names[0]
        for i, name in enumerate(sheet_names[1:], 1):
            comp.Sheets.insertNewByName(name, i)
        yield Doc(comp, path, fmt_of(path))
    finally:
        _close(comp, None)
