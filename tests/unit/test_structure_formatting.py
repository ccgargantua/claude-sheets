import contextlib
import io
import json
import os
import re
import tempfile
import unittest
import zipfile

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
import sys  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "src"))

from sheetcli.cli import main  # noqa: E402

RICH = ("xlsx", "ods")
_state = tempfile.TemporaryDirectory()


def setUpModule():
    os.environ["SHEETCLI_STATE_DIR"] = _state.name


def tearDownModule():
    run("stop")
    _state.cleanup()


def run(*argv, ok=True):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(argv))
    out = json.loads(buf.getvalue())
    assert (code == 0) == out["ok"], out
    assert out["ok"] == ok, out
    return out


def member(path, name):
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode()


def xlsx_sheet_xml(path, index):
    return member(path, f"xl/worksheets/sheet{index}.xml")


def ods_sheet_settings(path, sheet):
    xml = member(path, "settings.xml")
    m = re.search(rf'config-item-map-entry config:name="{sheet}">(.*?)</config:config-item-map-entry>', xml, re.S)
    return {k: int(v) for k, v in re.findall(
        r'config:name="(HorizontalSplit\w+|VerticalSplit\w+)" config:type="\w+">(\d+)<', m[1])}


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def make(self, ext, data='[["h","g"],[1,2],[3,4],[5,6]]', sheets="A,B,C"):
        sheets = "Sheet1" if ext == "csv" else sheets
        p = os.path.join(self._tmp.name, f"t.{ext}")
        if os.path.exists(p):
            os.remove(p)
        run("create", p, "--sheets", sheets)
        if data:
            run("write-range", p, "--start", "A1", "--data", data)
        return p

    def grid(self, p, rng=None, sheet=None, formulas=False):
        argv = ["read", p] + (["--range", rng] if rng else []) + (["--sheet", sheet] if sheet else [])
        return run(*argv, *(["--formulas"] if formulas else []))["data"]

    def each_rich(self):
        for ext in RICH:
            with self.subTest(ext=ext):
                yield ext, self.make(ext)


class SheetStructure(Base):
    def test_copy_sheet(self):
        for ext, p in self.each_rich():
            out = run("copy-sheet", p, "--name", "A", "--new-name", "A2", "--position", "1")
            self.assertEqual(out["sheets"], ["A2", "A", "B", "C"])
            self.assertEqual(self.grid(p, sheet="A2")[1], [1, 2])
            run("copy-sheet", p, "--name", "B", "--new-name", "B2")
            self.assertEqual(run("info", p)["sheets"][-1]["name"], "B2")
            run("copy-sheet", p, "--name", "B", "--new-name", "A", ok=False)
            run("copy-sheet", p, "--name", "B", "--new-name", "Z", "--position", "9", ok=False)

    def test_move_sheet(self):
        for ext, p in self.each_rich():
            self.assertEqual(run("move-sheet", p, "--name", "A", "--position", "3")["sheets"], ["B", "C", "A"])
            self.assertEqual(run("move-sheet", p, "--name", "A", "--position", "1")["sheets"], ["A", "B", "C"])
            self.assertEqual(run("move-sheet", p, "--name", "C", "--position", "2")["sheets"], ["A", "C", "B"])
            self.assertEqual([s["name"] for s in run("info", p)["sheets"]], ["A", "C", "B"])
            run("move-sheet", p, "--name", "A", "--position", "4", ok=False)

    def test_hide_show_sheet(self):
        for ext, p in self.each_rich():
            self.assertEqual(run("hide-sheet", p, "--name", "C")["hidden"], ["C"])
            self.assertEqual(run("hide-sheet", p, "--name", "A")["hidden"], ["A", "C"])
            run("hide-sheet", p, "--name", "B", ok=False)
            self.assertEqual(run("show-sheet", p, "--name", "C")["hidden"], ["A"])
            self.assertEqual(run("show-sheet", p, "--name", "A")["hidden"], [])
            run("hide-sheet", p, "--name", "nope", ok=False)

    def test_hide_active_sheet_keeps_file_valid(self):
        for ext, p in self.each_rich():
            self.assertEqual(run("hide-sheet", p, "--name", "A")["hidden"], ["A"])
            self.assertEqual(self.grid(p, sheet="B"), [])


class Hiding(Base):
    def test_hide_show_rows_cols(self):
        for ext, p in self.each_rich():
            run("hide-rows", p, "--rows", "2:3")
            run("hide-cols", p, "--cols", "B")
            if ext == "xlsx":
                xml = xlsx_sheet_xml(p, 1)
                self.assertEqual(len(re.findall(r'<row r="[23]"[^>]*hidden="true"', xml)), 2)
                self.assertEqual(len(re.findall(r'<row r="[14]"[^>]*hidden="true"', xml)), 0)
                self.assertRegex(xml, r'<col [^>]*hidden="true"[^>]*max="2" min="2"')
            else:
                self.assertIn('table:visibility="collapse"', member(p, "content.xml"))
            run("show-rows", p, "--rows", "2:3")
            run("show-cols", p, "--cols", "B")
            if ext == "xlsx":
                self.assertNotIn('hidden="true"', xlsx_sheet_xml(p, 1))
            else:
                self.assertNotIn("collapse", member(p, "content.xml"))
            run("hide-rows", p, "--rows", "x", ok=False)

    def test_other_sheet_untouched(self):
        for ext, p in self.each_rich():
            run("hide-rows", p, "--rows", "1", "--sheet", "B")
            if ext == "xlsx":
                self.assertNotIn('hidden="true"', xlsx_sheet_xml(p, 1))
                self.assertIn('hidden="true"', xlsx_sheet_xml(p, 2))


class Freeze(Base):
    def frozen(self, ext, p, index, sheet):
        if ext == "xlsx":
            m = re.search(r'<pane xSplit="(\d+)" ySplit="(\d+)"[^>]*state="frozen"', xlsx_sheet_xml(p, index))
            return (int(m[2]), int(m[1])) if m else None
        s = ods_sheet_settings(p, sheet)
        rows = s["VerticalSplitPosition"] if s.get("VerticalSplitMode") == 2 else 0
        cols = s["HorizontalSplitPosition"] if s.get("HorizontalSplitMode") == 2 else 0
        return (rows, cols) if rows or cols else None

    def test_freeze_unfreeze_persist(self):
        for ext, p in self.each_rich():
            run("freeze", p, "--cell", "C3", "--sheet", "B")
            self.assertEqual(self.frozen(ext, p, 2, "B"), (2, 2))
            self.assertIsNone(self.frozen(ext, p, 1, "A"))
            run("write", p, "--cell", "E1", "--value", "1")
            self.assertEqual(self.frozen(ext, p, 2, "B"), (2, 2), "freeze lost by a later save")
            run("freeze", p, "--cell", "A2", "--sheet", "B")
            self.assertEqual(self.frozen(ext, p, 2, "B"), (1, 0))
            run("unfreeze", p, "--sheet", "B")
            self.assertIsNone(self.frozen(ext, p, 2, "B"))

    def test_freeze_default_sheet_and_a1(self):
        for ext, p in self.each_rich():
            run("freeze", p, "--cell", "B1")
            self.assertEqual(self.frozen(ext, p, 1, "A"), (0, 1))
            run("freeze", p, "--cell", "A1", ok=False)


class CellOps(Base):
    def test_insert_delete_cols(self):
        for ext in ("xlsx", "ods", "csv"):
            with self.subTest(ext=ext):
                p = self.make(ext)
                run("insert-cols", p, "--at", "B", "--count", "2")
                self.assertEqual(self.grid(p, "A2:D2"), [[1, None, None, 2]])
                run("delete-cols", p, "--at", "B", "--count", "2")
                self.assertEqual(self.grid(p, "A2:B2"), [[1, 2]])
                run("insert-cols", p, "--at", "A", "--count", "0", ok=False)

    def test_clear(self):
        for ext in ("xlsx", "ods", "csv"):
            with self.subTest(ext=ext):
                p = self.make(ext)
                run("clear", p, "--range", "A2:A3", "--what", "contents")
                self.assertEqual(self.grid(p, "A1:A4"), [["h"], [None], [None], [5]])
                run("clear", p, "--range", "B1:B4")
                self.assertEqual(self.grid(p, "B1:B4"), [[None]] * 4)

    def test_clear_formats_keeps_values(self):
        for ext, p in self.each_rich():
            run("format", p, "--range", "A2", "--bold", "--fill", "FFFF00")
            run("clear", p, "--range", "A2", "--what", "formats")
            fmt = run("get-format", p, "--cell", "A2")
            self.assertFalse(fmt["font"]["bold"])
            self.assertIsNone(fmt["fill"])
            self.assertEqual(self.grid(p, "A2"), [[1]])
            run("format", p, "--range", "A3", "--bold")
            run("clear", p, "--range", "A3", "--what", "contents")
            self.assertTrue(run("get-format", p, "--cell", "A3")["font"]["bold"])

    def test_copy_move_range(self):
        for ext in ("xlsx", "ods", "csv"):
            with self.subTest(ext=ext):
                p = self.make(ext)
                run("write", p, "--cell", "C2", "--value", "=A2+B2")
                run("copy-range", p, "--src", "A2:C2", "--dst", "A4")
                self.assertEqual(self.grid(p, "A4:C4"), [[1, 2, 3]])
                self.assertEqual(self.grid(p, "A1:C1"), [["h", "g", None]])
                run("move-range", p, "--src", "A2:B2", "--dst", "E1")
                self.assertEqual(self.grid(p, "E1:F1"), [[1, 2]])
                self.assertEqual(self.grid(p, "A2:B2"), [[None, None]])
                run("copy-range", p, "--src", "A2", "--dst", "ZZZZ9", ok=False)

    def test_copy_move_across_sheets(self):
        for ext, p in self.each_rich():
            run("copy-range", p, "--src", "A1:B2", "--dst", "C3", "--dst-sheet", "B")
            self.assertEqual(self.grid(p, "C3:D4", "B"), [["h", "g"], [1, 2]])
            self.assertEqual(self.grid(p, "A1:B2"), [["h", "g"], [1, 2]])
            run("move-range", p, "--src", "A1:B2", "--dst", "A1", "--dst-sheet", "C")
            self.assertEqual(self.grid(p, "A1:B2", "C"), [["h", "g"], [1, 2]])
            self.assertEqual(self.grid(p, "A1:B2"), [[None, None]] * 2)
            run("copy-range", p, "--src", "A1", "--dst", "A1", "--dst-sheet", "nope", ok=False)

    def test_copy_range_keeps_formats(self):
        for ext, p in self.each_rich():
            run("format", p, "--range", "A1", "--bold", "--fill", "00FF00")
            run("copy-range", p, "--src", "A1", "--dst", "D1")
            fmt = run("get-format", p, "--cell", "D1")
            self.assertTrue(fmt["font"]["bold"])
            self.assertEqual(fmt["fill"], "00FF00")

    def test_fill_down_right_formulas_adjust(self):
        for ext in ("xlsx", "ods", "csv"):
            with self.subTest(ext=ext):
                p = self.make(ext, data='[[1,2,"=A1+B1"],[null,null,null],[null,null,null]]')
                run("fill", p, "--range", "A1:C3", "--mode", "down")
                self.assertEqual(self.grid(p, "A1:C3"), [[1, 2, 3]] * 3)
                if ext != "csv":
                    self.assertEqual(self.grid(p, "C3", formulas=True), [["=A3+B3"]])
                p = self.make(ext, data='[[1,null,null],[2,null,null]]')
                run("fill", p, "--range", "A1:C2", "--mode", "right")
                self.assertEqual(self.grid(p, "A1:C2"), [[1, 1, 1], [2, 2, 2]])

    def test_fill_series(self):
        for ext in ("xlsx", "ods", "csv"):
            with self.subTest(ext=ext):
                p = self.make(ext, data='[[10,5],[null,null],[null,null],[null,null]]')
                run("fill", p, "--range", "A1:B4", "--mode", "series", "--step", "2.5")
                self.assertEqual(self.grid(p, "A1:B4"), [[10, 5], [12.5, 7.5], [15, 10], [17.5, 12.5]])
                p = self.make(ext, data='[[1,null,null,null]]')
                run("fill", p, "--range", "A1:D1", "--mode", "series")
                self.assertEqual(self.grid(p, "A1:D1"), [[1, 2, 3, 4]])
                run("fill", p, "--range", "A1:D1", "--mode", "series", "--step", "-1")
                self.assertEqual(self.grid(p, "A1:D1"), [[1, 0, -1, -2]])

    def test_fill_errors(self):
        for ext, p in self.each_rich():
            run("fill", p, "--range", "A1", "--mode", "down", ok=False)
            run("fill", p, "--range", "A1:B1", "--mode", "down", ok=False)
            run("fill", p, "--range", "A1:A3", "--mode", "series", ok=False)


class Layout(Base):
    def test_row_height_and_autofit(self):
        for ext, p in self.each_rich():
            run("row-height", p, "--rows", "2:3", "--height", "30")
            self.assertAlmostEqual(run("get-format", p, "--cell", "A3")["row_height"], 30, delta=0.5)
            self.assertNotAlmostEqual(run("get-format", p, "--cell", "A4")["row_height"], 30, delta=1)
            run("row-height", p, "--rows", "2", "--height", "0", ok=False)
            run("write", p, "--cell", "A4", "--value", "a very long piece of text in one cell")
            before = run("get-format", p, "--cell", "A4")["col_width"]
            run("autofit", p, "--cols", "A")
            self.assertGreater(run("get-format", p, "--cell", "A4")["col_width"], before)
            run("autofit", p, "--rows", "2")
            self.assertLess(run("get-format", p, "--cell", "A2")["row_height"], 20)
            run("autofit", p, ok=False)

    def test_get_format(self):
        for ext, p in self.each_rich():
            run("format", p, "--range", "A1", "--bold", "--italic", "--underline", "--strike", "--wrap",
                "--font-name", "Courier New", "--font-size", "14", "--font-color", "#FF0000", "--fill", "00FF00",
                "--number-format", "0.00", "--align", "center", "--valign", "top", "--border", "outline",
                "--border-color", "0000FF")
            run("col-width", p, "--col", "A", "--width", "20")
            run("merge", p, "--range", "A1:B1")
            f = run("get-format", p, "--cell", "A1")
            self.assertEqual(f["font"], {"name": "Courier New", "size": 14.0, "bold": True, "italic": True,
                                         "underline": True, "strike": True, "color": "FF0000"})
            self.assertEqual((f["fill"], f["number_format"], f["align"], f["valign"], f["wrap"], f["merged"]),
                             ("00FF00", "0.00", "center", "top", True, "A1:B1"))
            self.assertEqual(f["borders"]["top"]["color"], "0000FF")
            self.assertAlmostEqual(f["col_width"], 20, delta=0.3)
            plain = run("get-format", p, "--cell", "A3")
            self.assertFalse(plain["font"]["bold"])
            self.assertIsNone(plain["fill"])
            self.assertFalse(plain["merged"])
            self.assertEqual(plain["borders"], {"top": None, "bottom": None, "left": None, "right": None})
            run("get-format", p, "--cell", "A1", "--sheet", "nope", ok=False)


class CondFormat(Base):
    def rules(self, ext, p):
        if ext == "xlsx":
            return re.findall(r"<conditionalFormatting.*?</conditionalFormatting>", xlsx_sheet_xml(p, 1), re.S)
        return re.findall(r"<calcext:conditional-format .*?</calcext:conditional-format>",
                          member(p, "content.xml"), re.S)

    def test_cond_format_each_condition(self):
        cases = [("gt", "1", None), ("lt", "1", None), ("ge", "1", None), ("le", "1", None), ("eq", "1", None),
                 ("ne", "x", None), ("between", "1", "3"), ("contains", "x", None), ("formula", "=A1>2", None)]
        for ext in RICH:
            for cond, v, v2 in cases:
                with self.subTest(ext=ext, cond=cond):
                    p = self.make(ext)
                    extra = ["--value2", v2] if v2 else []
                    run("cond-format", p, "--range", "A1:B4", "--condition", cond, "--value", v, *extra,
                        "--fill", "FF0000")
                    self.assertEqual(len(self.rules(ext, p)), 1)

    def test_cond_format_style_and_clear(self):
        for ext, p in self.each_rich():
            run("cond-format", p, "--range", "A2:A4", "--condition", "gt", "--value", "2",
                "--fill", "#FFC7CE", "--font-color", "9C0006", "--bold")
            if ext == "xlsx":
                styles = member(p, "xl/styles.xml")
                self.assertRegex(styles.upper(), "FFC7CE")
                self.assertRegex(styles.upper(), "9C0006")
                self.assertIn('operator="greaterThan"', xlsx_sheet_xml(p, 1))
            else:
                self.assertIn("sheetcli_cf", member(p, "content.xml"))
                styles = member(p, "styles.xml").upper()
                self.assertIn("FFC7CE", styles)
                self.assertIn("9C0006", styles)
            run("write", p, "--cell", "D1", "--value", "after")
            self.assertEqual(len(self.rules(ext, p)), 1, "rule lost by a later save")
            run("cond-format-clear", p, "--range", "A2:A4")
            self.assertEqual(self.rules(ext, p), [])

    def test_cond_format_clear_only_requested_range(self):
        for ext, p in self.each_rich():
            run("cond-format", p, "--range", "A1:A4", "--condition", "gt", "--value", "1", "--bold")
            run("cond-format", p, "--range", "B1:B4", "--condition", "lt", "--value", "9", "--bold")
            run("cond-format-clear", p, "--range", "A1:A4")
            rules = self.rules(ext, p)
            self.assertEqual(len(rules), 1)
            self.assertRegex(rules[0], r"B1:(A\.)?B4")

    def test_cond_format_errors(self):
        for ext, p in self.each_rich():
            run("cond-format", p, "--range", "A1", "--condition", "gt", "--value", "1", ok=False)
            run("cond-format", p, "--range", "A1", "--condition", "between", "--value", "1", "--bold", ok=False)
            run("cond-format", p, "--range", "A1", "--condition", "gt", "--value", "1", "--fill", "zz", ok=False)


class Autofilter(Base):
    def test_autofilter_on_off(self):
        for ext, p in self.each_rich():
            run("autofilter", p, "--range", "A1:B4")
            if ext == "xlsx":
                self.assertIn('<autoFilter ref="A1:B4"', member(p, "xl/tables/table1.xml"))
            else:
                self.assertIn('table:display-filter-buttons="true"', member(p, "content.xml"))
            run("write", p, "--cell", "D1", "--value", "x")
            if ext == "xlsx":
                self.assertIn("autoFilter", member(p, "xl/tables/table1.xml"))
            run("autofilter", p, "--range", "A1:B3")
            if ext == "xlsx":
                self.assertIn('ref="A1:B3"', member(p, "xl/tables/table1.xml"))
            out = run("autofilter", p, "--off")
            self.assertEqual(out["removed"], 1)
            if ext == "xlsx":
                self.assertNotIn("xl/tables/table1.xml", zipfile.ZipFile(p).namelist())
            else:
                self.assertNotIn("display-filter-buttons", member(p, "content.xml"))
            run("autofilter", p, ok=False)
            run("autofilter", p, "--range", "A1:B2", "--off", ok=False)


class CsvGating(Base):
    def test_rich_actions_unsupported_for_csv(self):
        p = self.make("csv")
        calls = [
            ("copy-sheet", "--name", "Sheet1", "--new-name", "X"), ("move-sheet", "--name", "Sheet1", "--position", "1"),
            ("hide-sheet", "--name", "Sheet1"), ("show-sheet", "--name", "Sheet1"),
            ("hide-rows", "--rows", "1"), ("show-rows", "--rows", "1"),
            ("hide-cols", "--cols", "A"), ("show-cols", "--cols", "A"),
            ("freeze", "--cell", "B2"), ("unfreeze",), ("autofilter", "--range", "A1:B2"),
            ("row-height", "--rows", "1", "--height", "20"), ("autofit", "--cols", "A"),
            ("get-format", "--cell", "A1"),
            ("cond-format", "--range", "A1", "--condition", "gt", "--value", "1", "--bold"),
            ("cond-format-clear", "--range", "A1"),
        ]
        for action, *rest in calls:
            with self.subTest(action=action):
                self.assertEqual(run(action, p, *rest, ok=False)["error"], "unsupported for csv")


class Flags(Base):
    def test_dry_run_and_backup(self):
        p = self.make("xlsx")
        run("hide-sheet", p, "--name", "C", "--dry-run")
        self.assertEqual(run("show-sheet", p, "--name", "C")["hidden"], [])
        out = run("copy-sheet", p, "--name", "A", "--new-name", "A2", "--backup")
        self.assertTrue(os.path.isfile(out["backup"]))


if __name__ == "__main__":
    unittest.main()
