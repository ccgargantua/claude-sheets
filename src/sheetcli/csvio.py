import csv

from .common import autotype
from .model import Book, MemSheet


class CsvBook(Book):
    fmt = "csv"
    formatting = False
    multi_sheet = False

    def __init__(self, rows=()):
        super().__init__()
        sheet = MemSheet("Sheet1")
        for r, row in enumerate(rows, 1):
            for c, v in enumerate(row, 1):
                sheet.set(r, c, autotype(v))
        self.sheets = [sheet]

    @classmethod
    def load(cls, path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            return cls(csv.reader(f))

    def save(self, path):
        s = self.sheets[0]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for r in range(1, s.max_row + 1):
                w.writerow([_fmt(s.get(r, c)) for c in range(1, s.max_col + 1)])


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v
