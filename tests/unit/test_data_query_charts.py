import functools
import os
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from test_sheet import RICH, Base, sheet  # noqa: E402

from sheetcli.document import open_doc  # noqa: E402
from sheetcli.uno_daemon import connection  # noqa: E402

_state = tempfile.TemporaryDirectory()
CHART_DATA = '[["cat","s1","s2"],["x",1,2],["y",3,4],["z",5,6]]'
ALL = ("xlsx", "ods", "csv")
ROWS = '[["name","qty","tag"],["a",5,"Paid"],["b",20,"open"],["c",30,"paid"],["a",5,"Paid"],["d","x","open"]]'


def setUpModule():
    os.environ["SHEETCLI_STATE_DIR"] = _state.name


def tearDownModule():
    sheet("stop")
    _state.cleanup()


def png(path, size=8):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * size for _ in range(size))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def inspect(path, fn):
    with connection() as desktop, open_doc(desktop, path) as doc:
        return fn(doc)


def forall(formats, data):
    def deco(fn):
        @functools.wraps(fn)
        def run(self):
            for ext in formats:
                with self.subTest(ext):
                    fn(self, self.make(ext, data))
                    self.assertNoLockFiles()
        return run
    return deco


class Rich(Base):
    pass


class NamesAndValidation(Rich):
    @forall(RICH, ROWS)
    def test_names(self, p):
        sheet("define-name", p, "--name", "Rng", "--range", "A1:B3")
        sheet("define-name", p, "--name", "Q", "--range", "Sheet1!B2:B4")
        self.assertEqual(sheet("names", p)["names"], [
            {"name": "Q", "range": "Sheet1!B2:B4"}, {"name": "Rng", "range": "Sheet1!A1:B3"}])
        self.assertIn("exists", self.err("define-name", p, "--name", "Q", "--range", "A1"))
        sheet("delete-name", p, "--name", "Rng")
        self.assertEqual([n["name"] for n in sheet("names", p)["names"]], ["Q"])
        self.assertIn("not found", self.err("delete-name", p, "--name", "nope"))

    @forall(RICH, ROWS)
    def test_define_name_sheet_qualified(self, p):
        sheet("add-sheet", p, "--name", "My Sheet")
        sheet("define-name", p, "--name", "X", "--range", "'My Sheet'!C3")
        self.assertEqual(sheet("names", p)["names"], [{"name": "X", "range": "My Sheet!C3"}])

    @forall(RICH, ROWS)
    def test_validation_list_and_clear(self, p):
        sheet("validation", p, "--range", "C2:C5", "--type", "list", "--values", "Paid,open")
        v = inspect(p, lambda d: d.sheet().getCellRangeByName("C3").Validation)
        self.assertEqual((v.Type.value, v.Formula1), ("LIST", '"Paid";"open"'))
        sheet("validation-clear", p, "--range", "C2:C5")
        v = inspect(p, lambda d: d.sheet().getCellRangeByName("C3").Validation)
        self.assertEqual(v.Type.value, "ANY")

    @forall(RICH, ROWS)
    def test_validation_numeric_and_date(self, p):
        sheet("validation", p, "--range", "B2:B3", "--type", "whole", "--min", "1", "--max", "10")
        sheet("validation", p, "--range", "B4", "--type", "decimal", "--min", "0.5")
        sheet("validation", p, "--range", "B5", "--type", "date", "--min", "2020-01-01")
        sheet("validation", p, "--range", "A2", "--type", "text-length", "--max", "3")

        def get(d):
            s = d.sheet()
            return [(c, s.getCellRangeByName(c).Validation) for c in ("B2", "B4", "B5", "A2")]
        (_, whole), (_, dec), (_, date), (_, tl) = inspect(p, get)
        self.assertEqual((whole.Type.value, whole.Operator.value, whole.Formula1, whole.Formula2),
                         ("WHOLE", "BETWEEN", "1", "10"))
        self.assertEqual((dec.Type.value, dec.Operator.value), ("DECIMAL", "GREATER_EQUAL"))
        self.assertEqual((date.Type.value, date.Formula1), ("DATE", "43831"))
        self.assertEqual((tl.Type.value, tl.Operator.value), ("TEXT_LEN", "LESS_EQUAL"))

    def test_validation_errors(self):
        p = self.make("xlsx", ROWS)
        self.assertIn("--values", self.err("validation", p, "--range", "A1", "--type", "list"))
        self.assertIn("--min", self.err("validation", p, "--range", "A1", "--type", "whole"))
        self.assertIn("bad", self.err("validation", p, "--range", "A1", "--type", "whole", "--min", "x"))


class CommentsLinksProtect(Rich):
    @forall(RICH, ROWS)
    def test_comment_roundtrip(self, p):
        sheet("comment", p, "--cell", "B2", "--text", "first")
        sheet("comment", p, "--cell", "B2", "--text", "second")

        def get(d):
            notes = d.sheet().Annotations
            return [(notes.getByIndex(i).String, notes.getByIndex(i).Position.Row)
                    for i in range(notes.Count)]
        self.assertEqual(inspect(p, get), [("second", 1)])
        sheet("delete-comment", p, "--cell", "B2")
        self.assertEqual(inspect(p, get), [])
        self.assertIn("no comment", self.err("delete-comment", p, "--cell", "B2"))

    @forall(RICH, ROWS)
    def test_hyperlink(self, p):
        sheet("hyperlink", p, "--cell", "E1", "--url", "http://example.com/x", "--text", "link")
        sheet("hyperlink", p, "--cell", "E2", "--url", "http://example.com/y")

        def get(d):
            out = []
            for ref in ("E1", "E2"):
                cell = d.sheet().getCellRangeByName(ref)
                fields = cell.Text.TextFields
                out.append((cell.String, [fields.getByIndex(i).URL for i in range(fields.Count)]))
            return out
        self.assertEqual(inspect(p, get), [("link", ["http://example.com/x"]),
                                           ("http://example.com/y", ["http://example.com/y"])])

    @forall(RICH, ROWS)
    def test_protect(self, p):
        sheet("protect", p, "--password", "pw")
        self.assertTrue(inspect(p, lambda d: d.sheet().isProtected()))
        self.assertIn("already", self.err("protect", p))
        self.assertIn("wrong password", self.err("unprotect", p, "--password", "bad"))
        sheet("unprotect", p, "--password", "pw")
        self.assertFalse(inspect(p, lambda d: d.sheet().isProtected()))
        self.assertIn("not protected", self.err("unprotect", p))

    def test_dry_run_and_backup(self):
        p = self.make("ods", ROWS)
        sheet("comment", p, "--cell", "A1", "--text", "t", "--dry-run")
        self.assertEqual(inspect(p, lambda d: d.sheet().Annotations.Count), 0)
        out = sheet("comment", p, "--cell", "A1", "--text", "t", "--backup")
        self.assertTrue(os.path.isfile(out["backup"]))


class Gating(Base):
    def test_csv_unsupported(self):
        p = self.make("csv", ROWS)
        argv = {
            "define-name": ["--name", "N", "--range", "A1"], "delete-name": ["--name", "N"], "names": [],
            "validation": ["--range", "A1", "--type", "list", "--values", "a"],
            "validation-clear": ["--range", "A1"], "comment": ["--cell", "A1", "--text", "t"],
            "delete-comment": ["--cell", "A1"], "hyperlink": ["--cell", "A1", "--url", "u"],
            "protect": [], "unprotect": [],
            "chart": ["--range", "A1:B2", "--type", "bar", "--anchor", "E1"],
            "delete-chart": ["--name", "c"], "charts": [], "image": ["--path", p, "--anchor", "E1"],
        }
        for name, extra in argv.items():
            with self.subTest(name):
                self.assertEqual(self.err(name, p, *extra), "unsupported for csv")


class Query(Base):
    def rows(self, p, *where, header=False):
        argv = ["filter", p] + [x for w in where for x in ("--where", w)] + (["--header"] if header else [])
        out = sheet(*argv)
        return [r["row"] for r in out["rows"]], out

    @forall(ALL, ROWS)
    def test_filter_numeric_string_and_and(self, p):
        self.assertEqual(self.rows(p, "B>5", header=True)[0], [3, 4])
        self.assertEqual(self.rows(p, "C==paid", header=True)[0], [2, 4, 5])
        self.assertEqual(self.rows(p, "C == paid", "B>=20", header=True)[0], [4])
        self.assertEqual(self.rows(p, "A contains A", header=True)[0], [2, 5])
        self.assertEqual(self.rows(p, "C!=paid", header=True)[0], [3, 6])
        rows, out = self.rows(p, "B<10", header=True)
        self.assertEqual((rows, out["header"]), ([2, 5], ["name", "qty", "tag"]))
        self.assertEqual(out["rows"][0]["values"], ["a", 5, "Paid"])

    @forall(ALL, ROWS)
    def test_filter_header_excluded_and_mixed_types(self, p):
        self.assertEqual(self.rows(p, "A==name")[0], [1])
        self.assertEqual(self.rows(p, "A==name", header=True)[0], [])
        self.assertEqual(self.rows(p, "B>1", header=True)[0], [2, 3, 4, 5])
        self.assertEqual(self.rows(p, "B<100", header=True)[0], [2, 3, 4, 5])
        self.assertEqual(self.rows(p, "B!=5", header=True)[0], [3, 4, 6])
        self.assertEqual(self.rows(p, "B==x", header=True)[0], [6])

    def test_filter_errors_and_readonly(self):
        p = self.make("xlsx", ROWS)
        before = os.path.getmtime(p)
        self.assertIn("bad --where", self.err("filter", p, "--where", "nonsense"))
        self.assertIn("beyond", self.err("filter", p, "--where", "Z>1"))
        sheet("filter", p, "--where", "B>1")
        self.assertEqual(os.path.getmtime(p), before)

    @forall(ALL, ROWS)
    def test_dedupe_all_columns(self, p):
        self.assertEqual(sheet("dedupe", p, "--header")["removed"], 1)
        self.assertEqual([r[0] for r in self.values(p)], ["name", "a", "b", "c", "d"])

    @forall(ALL, ROWS)
    def test_dedupe_cols_and_header(self, p):
        self.assertEqual(sheet("dedupe", p, "--cols", "C")["removed"], 2)
        self.assertEqual([r[0] for r in self.values(p)], ["name", "a", "b", "c"])

    @forall(ALL, ROWS)
    def test_dedupe_header_row_kept(self, p):
        sheet("write-range", p, "--start", "A7", "--data", '[["name","qty","tag"]]')
        self.assertEqual(sheet("dedupe", p, "--header")["removed"], 1)
        self.assertEqual(self.values(p)[0], ["name", "qty", "tag"])
        self.assertEqual(len(self.values(p)), 6)

    @forall(ALL, ROWS)
    def test_stats(self, p):
        out = sheet("stats", p, "--range", "B2:B6")
        self.assertEqual((out["count"], out["numeric_count"], out["sum"], out["min"], out["max"]),
                         (5, 4, 60, 5, 30))
        self.assertEqual(out["mean"], 15)
        empty = sheet("stats", p, "--range", "H1:H3")
        self.assertEqual((empty["count"], empty["numeric_count"], empty["mean"], empty["min"]),
                         (0, 0, None, None))


class Charts(Rich):
    @forall(RICH, CHART_DATA)
    def test_types_and_listing(self, p):
        want = {"bar": "bar", "column": "column", "line": "line", "pie": "pie",
                "scatter": "scatter", "area": "area"}
        for i, t in enumerate(want):
            out = sheet("chart", p, "--range", "A1:C4", "--type", t, "--anchor", f"F{1 + 20 * i}",
                        "--name", f"c_{t}", "--title", "T", "--header")
            self.assertEqual(out["name"], f"c_{t}")
        listed = {c["name"]: c for c in sheet("charts", p)["charts"]}
        self.assertEqual(len(listed), 6)
        for i, t in enumerate(want):
            c = listed[f"c_{t}"]
            self.assertEqual((c["type"], c["anchor"], c["sheet"]), (want[t], f"F{1 + 20 * i}", "Sheet1"))
            if t != "scatter":
                self.assertEqual(c["range"], "A1:C4")

    @forall(RICH, CHART_DATA)
    def test_header_flag_sets_labels(self, p):
        sheet("chart", p, "--range", "A1:C4", "--type", "column", "--anchor", "F1", "--name", "h", "--header")
        sheet("chart", p, "--range", "B2:C4", "--type", "column", "--anchor", "F30", "--name", "n")

        def get(d):
            charts = d.sheet().Charts
            return [(charts.getByIndex(i).HasColumnHeaders, charts.getByIndex(i).HasRowHeaders)
                    for i in range(charts.Count)]
        self.assertEqual(sorted(inspect(p, get)), [(False, False), (True, True)])

    @forall(RICH, CHART_DATA)
    def test_title_and_size_persist(self, p):
        sheet("chart", p, "--range", "A1:C4", "--type", "line", "--anchor", "F2", "--title", "Hello",
              "--width-mm", "100", "--height-mm", "50")

        def get(d):
            s = d.sheet()
            embedded = s.Charts.getByIndex(0).EmbeddedObject
            shape = s.DrawPage.getByIndex(0)
            return embedded.HasMainTitle, embedded.Title.String, shape.Size.Width, shape.Size.Height
        has, title, w, h = inspect(p, get)
        self.assertEqual((has, title), (True, "Hello"))
        self.assertAlmostEqual(w, 10000, delta=60)
        self.assertAlmostEqual(h, 5000, delta=60)

    @forall(RICH, CHART_DATA)
    def test_auto_name_unique_and_delete(self, p):
        a = sheet("chart", p, "--range", "A1:C4", "--type", "bar", "--anchor", "F1")["name"]
        b = sheet("chart", p, "--range", "A1:C4", "--type", "pie", "--anchor", "F20")["name"]
        self.assertNotEqual(a, b)
        self.assertIn("exists", self.err("chart", p, "--range", "A1:C4", "--type", "bar",
                                          "--anchor", "F40", "--name", a))
        sheet("delete-chart", p, "--name", a)
        self.assertEqual([c["name"] for c in sheet("charts", p)["charts"]], [b])
        self.assertIn("not found", self.err("delete-chart", p, "--name", a))

    @forall(RICH, CHART_DATA)
    def test_multi_sheet(self, p):
        sheet("add-sheet", p, "--name", "S2")
        sheet("chart", p, "--range", "A1:C4", "--type", "bar", "--anchor", "F1", "--name", "one")
        sheet("chart", p, "--range", "A1:C4", "--type", "bar", "--anchor", "F1", "--name", "two", "--sheet", "S2")
        self.assertEqual([c["sheet"] for c in sheet("charts", p)["charts"]], ["Sheet1", "S2"])
        self.assertEqual([c["name"] for c in sheet("charts", p, "--sheet", "S2")["charts"]], ["two"])
        sheet("delete-chart", p, "--name", "two")
        self.assertEqual([c["name"] for c in sheet("charts", p)["charts"]], ["one"])


class Images(Rich):
    def media(self, p):
        prefix = "xl/media/" if p.endswith(".xlsx") else "Pictures/"
        with zipfile.ZipFile(p) as z:
            return [n for n in z.namelist() if n.startswith(prefix)]

    @forall(RICH, None)
    def test_image_embedded_and_persists(self, p):
        img = self.path("pic.png")
        png(img)
        sheet("image", p, "--path", img, "--anchor", "D3", "--width-mm", "40", "--height-mm", "20")
        self.assertEqual(len(self.media(p)), 1)

        def get(d):
            s = d.sheet()
            shapes = [s.DrawPage.getByIndex(i) for i in range(s.DrawPage.Count)]
            pics = [x for x in shapes if x.ShapeType.endswith("GraphicObjectShape")]
            a = getattr(pics[0].Anchor, "CellAddress", None)
            return (len(pics), pics[0].Size.Width, pics[0].Size.Height, pics[0].Graphic.Linked,
                    a and (a.Column, a.Row))
        n, w, h, linked, anchor = inspect(p, get)
        self.assertEqual((n, linked), (1, False))
        self.assertAlmostEqual(w, 4000, delta=60)
        self.assertAlmostEqual(h, 2000, delta=60)
        if anchor:
            self.assertEqual(anchor, (3, 2))

    def test_image_survives_source_deletion(self):
        img = self.path("pic.png")
        png(img)
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext, None)
                sheet("image", p, "--path", img, "--anchor", "A1")
                moved = img + ".gone"
                os.rename(img, moved)
                try:
                    sheet("write", p, "--cell", "H1", "--value", "1")
                    self.assertEqual(len(self.media(p)), 1)
                finally:
                    os.rename(moved, img)

    def test_image_aspect_and_errors(self):
        img = self.path("pic.png")
        png(img)
        p = self.make("ods", None)
        out = sheet("image", p, "--path", img, "--anchor", "A1", "--width-mm", "30")
        self.assertEqual((out["width_mm"], out["height_mm"]), (30, 30))
        self.assertIn("not found", self.err("image", p, "--path", self.path("nope.png"), "--anchor", "A1"))
        bad = self.path("bad.png")
        with open(bad, "wb") as f:
            f.write(b"not an image")
        self.assertIn("unreadable", self.err("image", p, "--path", bad, "--anchor", "A1"))


if __name__ == "__main__":
    unittest.main()
