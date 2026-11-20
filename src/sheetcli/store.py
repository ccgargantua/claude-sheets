import os

from .common import SheetError, check_input_file, check_sheet_name

EXTS = (".xlsx", ".ods", ".csv")


def fmt_of(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in EXTS:
        raise SheetError(f"unsupported file type {ext or '(none)'}; use .xlsx, .ods or .csv")
    return ext[1:]


def open_book(path):
    fmt = fmt_of(path)
    check_input_file(path)
    if fmt == "xlsx":
        from .xlsx import XlsxBook
        return XlsxBook.load(path)
    if fmt == "ods":
        from .ods import OdsBook
        return OdsBook.load(path)
    from .csvio import CsvBook
    try:
        return CsvBook.load(path)
    except (UnicodeDecodeError, OSError) as e:
        raise SheetError(f"cannot read csv: {e}")


def new_book(path, names):
    fmt = fmt_of(path)
    for n in names:
        check_sheet_name(n)
    if len(set(names)) != len(names):
        raise SheetError("duplicate sheet names")
    if fmt == "xlsx":
        from .xlsx import XlsxBook
        return XlsxBook.new(names)
    if fmt == "ods":
        from .ods import OdsBook
        return OdsBook.new(names)
    from .csvio import CsvBook
    if len(names) > 1:
        raise SheetError("unsupported for csv")
    return CsvBook()


def save_book(book, path):
    tmp = path + ".sheetcli.tmp"
    try:
        book.save(tmp)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
