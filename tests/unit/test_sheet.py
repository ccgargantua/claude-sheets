import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from sheetcli.cli import build_parser, main  # noqa: E402

FORMATS = ("xlsx", "ods", "csv")
DATA = '[["name","qty"],["b",2],["a",1.5],["c",3]]'


def sheet(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(argv))
    out = json.loads(buf.getvalue())
    assert (code == 0) == out["ok"], out
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def path(self, name):
        return os.path.join(self._tmp.name, name)

    def make(self, ext, data=DATA, sheets="Sheet1"):
        p = self.path(f"t.{ext}")
        if os.path.exists(p):
            os.remove(p)
        sheet("create", p, "--sheets", sheets)
        if data:
            sheet("write-range", p, "--start", "A1", "--data", data)
        return p

    def err(self, *argv):
        out = sheet(*argv)
        self.assertFalse(out["ok"])
        return out["error"]


class DataActions(Base):
    def test_parser_importable(self):
        self.assertEqual(build_parser().parse_args(["info", "x.csv"]).action, "info")

    def test_create_info_read(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                info = sheet("info", p)
                self.assertEqual(info["format"], ext)
                self.assertEqual(info["sheets"], [{"name": "Sheet1", "rows": 4, "cols": 2}])
                out = sheet("read", p)
                self.assertEqual(out["range"], "A1:B4")
                self.assertEqual(out["data"][1:3], [["b", 2], ["a", 1.5]])
                self.assertEqual(sheet("read", p, "--range", "B2:B3")["data"], [[2], [1.5]])
                self.assertEqual(sheet("read", p, "--as", "csv", "--range", "A1:B2")["csv"], "name,qty\nb,2\n")

    def test_create_exists_and_bad_ext(self):
        p = self.make("csv")
        self.assertIn("exists", self.err("create", p))
        self.assertIn("unsupported file type", self.err("create", self.path("x.txt")))
        self.assertIn("not found", self.err("info", self.path("nope.xlsx")))

    def test_write_types_and_formula(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext, data=None)
                for cell, v in (("A1", "7"), ("B1", "2.5"), ("C1", "true"), ("D1", "hi"), ("E1", "=A1+B1")):
                    sheet("write", p, "--cell", cell, "--value", v)
                self.assertEqual(sheet("read", p)["data"], [[7, 2.5, True, "hi", "=A1+B1"]])
                sheet("write", p, "--cell", "A1", "--value", "")
                self.assertIsNone(sheet("read", p, "--range", "A1")["data"][0][0])

    def test_write_range_and_append(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext, data=None)
                self.assertEqual(sheet("write-range", p, "--start", "B2", "--data", '[[1,2],[3,4]]')["range"], "B2:C3")
                out = sheet("append", p, "--data", '[["x",true]]')
                self.assertEqual(out["row"], 4)
                self.assertEqual(sheet("read", p, "--range", "A4:B4")["data"], [["x", True]])

    def test_data_errors(self):
        p = self.make("csv")
        self.assertIn("JSON", self.err("append", p, "--data", "[["))
        self.assertIn("2D", self.err("append", p, "--data", "[1,2]"))

    def test_rows(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                sheet("insert-rows", p, "--at", "2", "--count", "2")
                d = sheet("read", p)["data"]
                self.assertEqual(d[0][0], "name")
                self.assertEqual(d[1], [None, None])
                self.assertEqual(d[3], ["b", 2])
                sheet("delete-rows", p, "--at", "2", "--count", "2")
                self.assertEqual(sheet("read", p)["data"][1], ["b", 2])
                self.assertIn(">= 1", self.err("insert-rows", p, "--at", "0"))

    def test_find(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                self.assertEqual([m["cell"] for m in sheet("find", p, "--query", "A")["matches"]], ["A1", "A3"])
                self.assertEqual(sheet("find", p, "--query", "NAME", "--exact")["count"], 0)
                self.assertEqual(sheet("find", p, "--query", "name", "--exact")["count"], 1)
                self.assertEqual(sheet("find", p, "--query", "1.5")["matches"][0]["cell"], "B3")

    def test_sort(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                sheet("sort", p, "--by", "A", "--header")
                self.assertEqual([r[0] for r in sheet("read", p)["data"]], ["name", "a", "b", "c"])
                sheet("sort", p, "--by", "B", "--desc", "--header")
                self.assertEqual([r[1] for r in sheet("read", p)["data"]], ["qty", 3, 2, 1.5])
                sheet("sort", p, "--by", "A", "--desc")
                self.assertEqual(sheet("read", p)["data"][0][0], "name")

    def test_unknown_sheet(self):
        p = self.make("xlsx")
        self.assertIn("sheet not found", self.err("read", p, "--sheet", "Nope"))


class SheetActions(Base):
    def test_multi_sheet(self):
        for ext in ("xlsx", "ods"):
            with self.subTest(ext):
                p = self.make(ext, sheets="One,Two")
                self.assertEqual(sheet("add-sheet", p, "--name", "Three")["sheets"], ["One", "Two", "Three"])
                sheet("write", p, "--cell", "A1", "--value", "x", "--sheet", "Two")
                self.assertEqual(sheet("read", p, "--sheet", "Two")["data"], [["x"]])
                self.assertEqual(sheet("read", p)["data"][0][0], "name")
                self.assertEqual(sheet("rename-sheet", p, "--name", "Two", "--new-name", "Dos")["sheets"], ["One", "Dos", "Three"])
                self.assertEqual(sheet("read", p, "--sheet", "Dos")["data"], [["x"]])
                self.assertEqual(sheet("delete-sheet", p, "--name", "One")["sheets"], ["Dos", "Three"])
                self.assertIn("already exists", self.err("add-sheet", p, "--name", "Dos"))
                self.assertIn("invalid sheet name", self.err("add-sheet", p, "--name", "a/b"))
                sheet("delete-sheet", p, "--name", "Dos")
                self.assertIn("only sheet", self.err("delete-sheet", p, "--name", "Three"))

    def test_csv_unsupported(self):
        p = self.make("csv")
        for argv in (("add-sheet", p, "--name", "X"), ("delete-sheet", p, "--name", "Sheet1"),
                     ("rename-sheet", p, "--name", "Sheet1", "--new-name", "Y"),
                     ("format", p, "--range", "A1", "--bold"), ("col-width", p, "--col", "A", "--width", "5"),
                     ("merge", p, "--range", "A1:B1"), ("unmerge", p, "--range", "A1:B1"),
                     ("create", self.path("m.csv"), "--sheets", "A,B")):
            with self.subTest(argv[0]):
                self.assertEqual(self.err(*argv), "unsupported for csv")


class Formatting(Base):
    def load(self, p):
        from sheetcli.store import open_book
        return open_book(p).sheet()

    def test_format_roundtrip(self):
        for ext in ("xlsx", "ods"):
            with self.subTest(ext):
                p = self.make(ext)
                out = sheet("format", p, "--range", "A1:B1", "--bold", "--italic", "--underline",
                            "--font-size", "14", "--font-color", "#00ff00", "--fill", "FFFF00",
                            "--number-format", "#,##0.00", "--align", "center")
                self.assertEqual(out["range"], "A1:B1")
                s = self.load(p)
                fmts = dict(s.style_items())
                self.assertEqual(fmts[(1, 2)], {
                    "bold": True, "italic": True, "underline": True, "font_size": 14,
                    "font_color": "00FF00", "fill": "FFFF00", "number_format": "#,##0.00", "align": "center"})
                self.assertNotIn((2, 1), fmts)
                self.assertEqual(sheet("read", p)["data"][1], ["b", 2])

    def test_format_errors(self):
        p = self.make("xlsx")
        self.assertIn("no format options", self.err("format", p, "--range", "A1"))
        self.assertIn("bad hex", self.err("format", p, "--range", "A1", "--fill", "zz"))
        self.assertIn("bad cell", self.err("format", p, "--range", "1A", "--bold"))
        q = self.make("ods")
        self.assertIn("not supported in ods", self.err("format", q, "--range", "A1", "--number-format", "yyyy-mm-dd"))

    def test_format_keeps_prior(self):
        for ext in ("xlsx", "ods"):
            with self.subTest(ext):
                p = self.make(ext)
                sheet("format", p, "--range", "A1", "--bold")
                sheet("format", p, "--range", "A1", "--fill", "ff0000")
                self.assertEqual(dict(self.load(p).style_items())[(1, 1)], {"bold": True, "fill": "FF0000"})

    def test_col_width(self):
        for ext in ("xlsx", "ods"):
            with self.subTest(ext):
                p = self.make(ext)
                sheet("col-width", p, "--col", "B", "--width", "25")
                self.assertAlmostEqual(dict(self.load(p).width_items())[2], 25, delta=0.1)
                self.assertIn("> 0", self.err("col-width", p, "--col", "B", "--width", "0"))

    def test_merge_unmerge(self):
        for ext in ("xlsx", "ods"):
            with self.subTest(ext):
                p = self.make(ext)
                sheet("merge", p, "--range", "D1:E2")
                self.assertEqual(self.load(p).merges(), ["D1:E2"])
                self.assertIn("overlaps", self.err("merge", p, "--range", "E2:F3"))
                self.assertIn("more than one", self.err("merge", p, "--range", "A1"))
                sheet("insert-rows", p, "--at", "1")
                self.assertEqual(self.load(p).merges(), ["D2:E3"])
                self.assertEqual(sheet("unmerge", p, "--range", "E3")["unmerged"], 1)
                self.assertEqual(self.load(p).merges(), [])

    def test_ods_formula_conversion(self):
        from sheetcli.ods import from_ods_formula, to_ods_formula
        f = '=IF(A1>1,SUM(B1:B3),"a,B2")'
        self.assertEqual(to_ods_formula(f), 'of:=IF([.A1]>1;SUM([.B1:.B3]);"a,B2")')
        self.assertEqual(from_ods_formula(to_ods_formula(f)), f)


class Convert(Base):
    def test_all_directions(self):
        for src in FORMATS:
            for dst in FORMATS:
                with self.subTest(f"{src}->{dst}"):
                    p = self.make(src)
                    q = self.path(f"out.{dst}")
                    out = sheet("convert", p, q)
                    self.assertEqual(out["dst"], q)
                    self.assertEqual(sheet("read", q)["data"], sheet("read", p)["data"])

    def test_formatting_survives_xlsx_ods(self):
        p = self.make("xlsx")
        sheet("format", p, "--range", "A1", "--bold", "--fill", "ff0000")
        sheet("col-width", p, "--col", "A", "--width", "30")
        sheet("merge", p, "--range", "D1:E1")
        q, r = self.path("o.ods"), self.path("o.xlsx")
        sheet("convert", p, q)
        sheet("convert", q, r)
        from sheetcli.store import open_book
        s = open_book(r).sheet()
        self.assertEqual(dict(s.style_items())[(1, 1)], {"bold": True, "fill": "FF0000"})
        self.assertAlmostEqual(dict(s.width_items())[1], 30, delta=0.1)
        self.assertEqual(s.merges(), ["D1:E1"])

    def test_multi_sheet_to_csv_and_errors(self):
        p = self.make("xlsx", sheets="One,Two")
        out = sheet("convert", p, self.path("o.csv"))
        self.assertEqual(out["skipped_sheets"], ["Two"])
        self.assertIn("same file", self.err("convert", p, p))
        self.assertIn("unsupported file type", self.err("convert", p, self.path("o.txt")))

    def test_multi_sheet_xlsx_ods(self):
        p = self.make("xlsx", sheets="One,Two")
        sheet("write", p, "--cell", "A1", "--value", "z", "--sheet", "Two")
        q = self.path("o.ods")
        self.assertEqual(sheet("convert", p, q)["sheets"], ["One", "Two"])
        self.assertEqual(sheet("read", q, "--sheet", "Two")["data"], [["z"]])


class Limits(Base):
    def test_size_limits(self):
        from sheetcli import common
        p = self.make("csv")
        old = common.MAX_FILE
        common.MAX_FILE = 5
        try:
            self.assertIn("too large", self.err("info", p))
        finally:
            common.MAX_FILE = old
        x = self.make("xlsx")
        old = common.MAX_UNZIPPED
        common.MAX_UNZIPPED = 10
        try:
            self.assertIn("uncompressed", self.err("info", x))
        finally:
            common.MAX_UNZIPPED = old

    def test_garbage_files_give_json_errors(self):
        for ext in ("xlsx", "ods"):
            p = self.path(f"bad.{ext}")
            with open(p, "wb") as f:
                f.write(b"not a zip")
            self.assertTrue(self.err("info", p))

    def test_bad_args_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            build_parser().parse_args(["read"])
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(json.loads(buf.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
