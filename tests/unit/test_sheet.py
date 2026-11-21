import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from sheetcli.actions import HANDLERS  # noqa: E402
from sheetcli.cli import build_parser, main  # noqa: E402

FORMATS = ("xlsx", "ods", "csv")
RICH = ("xlsx", "ods")
DATA = '[["name","qty"],["b",2],["a",1.5],["c",3]]'
_state = tempfile.TemporaryDirectory()


def setUpModule():
    os.environ["SHEETCLI_STATE_DIR"] = _state.name


def tearDownModule():
    sheet("stop")
    _state.cleanup()


def run_main(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(argv))
    out = json.loads(buf.getvalue())
    assert (code == 0) == out["ok"], out
    return out


def sheet(*argv):
    return run_main(*argv)


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

    def values(self, p, *extra):
        return sheet("read", p, *extra)["data"]

    def assertNoLockFiles(self):
        stray = [n for n in os.listdir(self._tmp.name) if n.startswith(".~lock") or ".sheetcli-" in n]
        self.assertEqual(stray, [])


class ParserTests(unittest.TestCase):
    def test_61_actions_and_flags(self):
        parser = build_parser()
        sub = next(a for a in parser._actions if a.dest == "action").choices
        self.assertEqual(len(sub), 61)
        for name, handler in HANDLERS.items():
            flags = {o for a in sub[name]._actions for o in a.option_strings}
            self.assertEqual({"--dry-run", "--backup"} <= flags, handler.mutates, name)

    def test_parse_samples(self):
        p = build_parser()
        a = p.parse_args(["format", "f.xlsx", "--range", "A1", "--no-bold", "--border", "all", "--valign", "top"])
        self.assertTrue(a.no_bold)
        self.assertEqual((a.border, a.valign, a.dry_run), ("all", "top", False))
        self.assertEqual(p.parse_args(["filter", "f.csv", "--where", "A>1", "--where", "B==x"]).where, ["A>1", "B==x"])
        self.assertEqual(p.parse_args(["status"]).action, "status")
        self.assertTrue(p.parse_args(["read", "f.csv", "--formulas"]).formulas)

    def test_import_without_uno(self):
        code = "import sys; sys.path.insert(0, %r); from sheetcli.cli import build_parser; build_parser(); " \
               "assert 'uno' not in sys.modules" % os.path.join(ROOT, "src")
        subprocess.run([sys.executable, "-c", code], check=True)

    def test_bad_args_json(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            build_parser().parse_args(["read"])
        self.assertEqual(cm.exception.code, 1)
        self.assertFalse(json.loads(buf.getvalue())["ok"])


class Stubs(Base):
    def test_unimplemented_reports_error(self):
        p = self.make("xlsx")
        argv = {"insert-cols": ["--at", "A"], "chart": ["--range", "A1:B2", "--type", "bar", "--anchor", "D1"]}
        for name, h in HANDLERS.items():
            if h.fn is None and name in argv:
                with self.subTest(name):
                    self.assertEqual(self.err(name, p, *argv[name]), f"not implemented: {name}")


class DataActions(Base):
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
                self.assertEqual(self.values(p, "--range", "B2:B3"), [[2], [1.5]])
                self.assertEqual(sheet("read", p, "--as", "csv", "--range", "A1:B2")["csv"], "name,qty\nb,2\n")
                self.assertNoLockFiles()

    def test_empty_sheet(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext, data=None)
                self.assertEqual(sheet("info", p)["sheets"], [{"name": "Sheet1", "rows": 0, "cols": 0}])
                out = sheet("read", p)
                self.assertEqual((out["range"], out["data"]), (None, []))

    def test_create_exists_and_bad_ext(self):
        p = self.make("csv")
        self.assertIn("exists", self.err("create", p))
        self.assertIn("unsupported file type", self.err("create", self.path("x.txt")))
        self.assertIn("not found", self.err("info", self.path("nope.xlsx")))
        self.assertEqual(self.err("create", self.path("m.csv"), "--sheets", "A,B"), "unsupported for csv")

    def test_write_types(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext, data=None)
                for cell, v in (("A1", "7"), ("B1", "2.5"), ("C1", "true"), ("D1", "hi"), ("E1", "007")):
                    sheet("write", p, "--cell", cell, "--value", v)
                row = self.values(p)[0]
                self.assertEqual(row[:4], [7, 2.5, True, "hi"] if ext != "csv" else [7, 2.5, True, "hi"])
                if ext != "csv":
                    self.assertEqual(row[4], "007")
                sheet("write", p, "--cell", "A1", "--value", "")
                self.assertIsNone(self.values(p, "--range", "A1")[0][0])

    def test_formulas_computed_and_text(self):
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext, data=None)
                sheet("write", p, "--cell", "A1", "--value", "4")
                sheet("write", p, "--cell", "A2", "--value", "6")
                sheet("write", p, "--cell", "A3", "--value", '=IF(SUM(A1:A2)>5,"big","small")')
                sheet("write", p, "--cell", "A4", "--value", "=A1/0")
                sheet("write", p, "--cell", "A5", "--value", "=A1>1")
                self.assertEqual(self.values(p, "--range", "A3:A5"), [["big"], ["#DIV/0!"], [True]])
                f = self.values(p, "--range", "A3:A4", "--formulas")
                self.assertEqual(f, [['=IF(SUM(A1:A2)>5,"big","small")'], ["=A1/0"]])

    def test_cross_sheet_formula(self):
        p = self.make("xlsx", data=None, sheets="One,Two")
        sheet("write", p, "--cell", "B3", "--value", "7", "--sheet", "Two")
        sheet("write", p, "--cell", "A1", "--value", "=Two!B3*2")
        self.assertEqual(self.values(p, "--range", "A1"), [[14]])

    def test_dates_read_as_iso(self):
        p = self.make("xlsx", data=None)
        sheet("write", p, "--cell", "A1", "--value", "45000")
        sheet("format", p, "--range", "A1", "--number-format", "yyyy-mm-dd")
        self.assertEqual(self.values(p), [["2023-03-15"]])

    def test_write_range_and_append(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext, data=None)
                self.assertEqual(sheet("write-range", p, "--start", "B2", "--data", "[[1,2],[3,4]]")["range"], "B2:C3")
                out = sheet("append", p, "--data", '[["x",true]]')
                self.assertEqual(out["row"], 4)
                self.assertEqual(self.values(p, "--range", "A4:B4"), [["x", True]])

    def test_data_errors(self):
        p = self.make("csv")
        self.assertIn("JSON", self.err("append", p, "--data", "[["))
        self.assertIn("2D", self.err("append", p, "--data", "[1,2]"))

    def test_rows(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                sheet("insert-rows", p, "--at", "2", "--count", "2")
                d = self.values(p)
                self.assertEqual((d[0][0], d[1], d[3]), ("name", [None, None], ["b", 2]))
                sheet("delete-rows", p, "--at", "2", "--count", "2")
                self.assertEqual(self.values(p)[1], ["b", 2])
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
                self.assertEqual([r[0] for r in self.values(p)], ["name", "a", "b", "c"])
                sheet("sort", p, "--by", "B", "--desc", "--header")
                self.assertEqual([r[1] for r in self.values(p)], ["qty", 3, 2, 1.5])
                sheet("sort", p, "--by", "A", "--desc")
                self.assertEqual(self.values(p)[0][0], "name")

    def test_sort_empty_last(self):
        p = self.make("xlsx", data='[["b"],[null],["a"]]')
        sheet("sort", p, "--by", "A", "--desc")
        self.assertEqual(self.values(p, "--range", "A1:A3"), [["b"], ["a"], [None]])

    def test_unknown_sheet(self):
        p = self.make("xlsx")
        self.assertIn("sheet not found", self.err("read", p, "--sheet", "Nope"))

    def test_recalc(self):
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext, data='[[1,2],["=A1+B1"]]')
                self.assertEqual(sheet("recalc", p), {"ok": True, "recalculated": True})
                self.assertEqual(self.values(p, "--range", "A2"), [[3]])


class SheetActions(Base):
    def test_multi_sheet(self):
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext, sheets="One,Two")
                self.assertEqual(sheet("add-sheet", p, "--name", "Three")["sheets"], ["One", "Two", "Three"])
                sheet("write", p, "--cell", "A1", "--value", "x", "--sheet", "Two")
                self.assertEqual(self.values(p, "--sheet", "Two"), [["x"]])
                self.assertEqual(self.values(p)[0][0], "name")
                self.assertEqual(sheet("rename-sheet", p, "--name", "Two", "--new-name", "Dos")["sheets"],
                                 ["One", "Dos", "Three"])
                self.assertEqual(self.values(p, "--sheet", "Dos"), [["x"]])
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
                     ("merge", p, "--range", "A1:B1"), ("unmerge", p, "--range", "A1:B1")):
            with self.subTest(argv[0]):
                self.assertEqual(self.err(*argv), "unsupported for csv")


class Formatting(Base):
    def test_format_applies_and_keeps_values(self):
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext)
                out = sheet("format", p, "--range", "A1:B1", "--bold", "--italic", "--underline", "--strike",
                            "--wrap", "--font-size", "14", "--font-name", "Arial", "--font-color", "#00ff00",
                            "--fill", "FFFF00", "--number-format", "#,##0.00", "--align", "center",
                            "--valign", "top", "--border", "all", "--border-color", "ff0000")
                self.assertEqual(out["range"], "A1:B1")
                self.assertEqual(out["applied"], sorted(
                    ["bold", "italic", "underline", "strike", "wrap", "font_size", "font_name", "font_color",
                     "fill", "number_format", "align", "valign", "border"]))
                self.assertEqual(self.values(p)[1], ["b", 2])

    def test_format_errors(self):
        p = self.make("xlsx")
        self.assertIn("no format options", self.err("format", p, "--range", "A1"))
        self.assertIn("bad hex", self.err("format", p, "--range", "A1", "--fill", "zz"))
        self.assertIn("bad cell", self.err("format", p, "--range", "1A", "--bold"))
        self.assertIn("conflict", self.err("format", p, "--range", "A1", "--bold", "--no-bold"))
        self.assertIn("requires --border", self.err("format", p, "--range", "A1", "--border-color", "ff0000"))

    def test_number_format_changes_display_type(self):
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext, data="[[45000]]")
                sheet("format", p, "--range", "A1", "--number-format", "yyyy-mm-dd")
                self.assertEqual(self.values(p), [["2023-03-15"]])
                sheet("format", p, "--range", "A1", "--number-format", "General")
                self.assertEqual(self.values(p), [[45000]])

    def test_col_width_char_units(self):
        from sheetcli.document import open_doc
        from sheetcli.uno_daemon import connection
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext)
                sheet("col-width", p, "--col", "B", "--width", "25")
                with connection() as desktop, open_doc(desktop, p) as doc:
                    mm100 = doc.sheet().Columns.getByIndex(1).Width
                self.assertAlmostEqual(mm100 / 230, 25, delta=1.5)
                self.assertIn("> 0", self.err("col-width", p, "--col", "B", "--width", "0"))

    def test_merge_unmerge(self):
        for ext in RICH:
            with self.subTest(ext):
                p = self.make(ext, data='[["a","b","c","d","e"]]')
                sheet("merge", p, "--range", "A1:B1")
                self.assertEqual(self.values(p, "--range", "A1:B1"), [["a", None]])
                self.assertIn("overlaps", self.err("merge", p, "--range", "B1:C2"))
                self.assertIn("more than one", self.err("merge", p, "--range", "D1"))
                sheet("merge", p, "--range", "D1:E1")
                self.assertEqual(sheet("unmerge", p, "--range", "A1:E1")["unmerged"], 2)
                self.assertEqual(sheet("unmerge", p, "--range", "A1:E1")["unmerged"], 0)


class Convert(Base):
    def test_all_directions(self):
        for src in FORMATS:
            for dst in FORMATS:
                with self.subTest(f"{src}->{dst}"):
                    p = self.make(src)
                    q = self.path(f"out.{dst}")
                    out = sheet("convert", p, q)
                    self.assertEqual(out["dst"], q)
                    self.assertEqual(self.values(q), self.values(p))

    def test_formatting_survives_xlsx_ods(self):
        p = self.make("xlsx")
        sheet("merge", p, "--range", "D1:E1")
        q, r = self.path("o.ods"), self.path("o.xlsx")
        sheet("convert", p, q)
        sheet("convert", q, r)
        self.assertIn("overlaps", self.err("merge", r, "--range", "E1:F1"))

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
        self.assertEqual(self.values(q, "--sheet", "Two"), [["z"]])

    def test_csv_text_not_all_quoted(self):
        p = self.make("csv")
        with open(p, encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines()[0], "name,qty")


class Batch(Base):
    def ops(self, *ops):
        return json.dumps(list(ops))

    def test_batch_applies_all_and_saves_once(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                out = sheet("batch", p, "--ops", self.ops(
                    {"action": "write", "cell": "D1", "value": "9"},
                    {"action": "append", "data": [["z", 5]]},
                    {"action": "read", "range": "A5:B5"},
                    {"action": "sort", "by": "A", "header": True, "desc": True}))
                self.assertEqual(out["count"], 4)
                self.assertEqual(out["results"][2]["data"], [["z", 5]])
                self.assertEqual(self.values(p)[1][0], "z")
                self.assertEqual(self.values(p, "--range", "D1"), [[9]])

    def test_batch_atomic_failure(self):
        p = self.make("xlsx")
        before = self.values(p)
        out = sheet("batch", p, "--ops", self.ops(
            {"action": "write", "cell": "A1", "value": "changed"},
            {"action": "format", "range": "A1", "bold": True},
            {"action": "write", "cell": "1A", "value": "x"}))
        self.assertFalse(out["ok"])
        self.assertEqual((out["op"], out["action"]), (2, "write"))
        self.assertIn("op 2 (write)", out["error"])
        self.assertEqual(self.values(p), before)

    def test_batch_validation_failures_do_not_touch_file(self):
        p = self.make("xlsx")
        before = self.values(p)
        for ops, text in (
            ([{"action": "create"}], "not allowed in batch"),
            ([{"action": "write", "cell": "A1", "value": "x"}, {"action": "batch"}], "not allowed in batch"),
            ([{"action": "nope"}], "unknown action"),
            ([{"action": "write", "cell": "A1"}], "required"),
            ([{"action": "write", "cell": "A1", "value": "1", "dry_run": True}], "not allowed in an op"),
            ([], "non-empty"),
        ):
            with self.subTest(text):
                self.assertIn(text, self.err("batch", p, "--ops", json.dumps(ops)))
        self.assertEqual(self.values(p), before)

    def test_ops_file_and_csv_gating(self):
        p = self.make("csv")
        f = self.path("ops.json")
        with open(f, "w") as fh:
            json.dump([{"action": "write", "cell": "A1", "value": "q"}], fh)
        sheet("batch", p, "--ops-file", f)
        self.assertEqual(self.values(p, "--range", "A1"), [["q"]])
        out = sheet("batch", p, "--ops", self.ops({"action": "format", "range": "A1", "bold": True}))
        self.assertIn("unsupported for csv", out["error"])
        self.assertEqual(out["op"], 0)

    def test_where_repeatable_and_unimplemented_flags(self):
        p = self.make("xlsx")
        out = sheet("batch", p, "--ops", self.ops({"action": "read", "formulas": True}))
        self.assertEqual(out["results"][0]["range"], "A1:B4")


class DryRunBackup(Base):
    def snapshot(self, p):
        with open(p, "rb") as f:
            return f.read()

    def test_dry_run_does_not_save(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                before = self.snapshot(p)
                out = sheet("write", p, "--cell", "A1", "--value", "zzz", "--dry-run")
                self.assertTrue(out["dry_run"])
                self.assertEqual(self.snapshot(p), before)
                self.assertEqual(self.values(p)[0][0], "name")
                b = sheet("batch", p, "--ops", json.dumps([{"action": "write", "cell": "A1", "value": "q"}]), "--dry-run")
                self.assertTrue(b["dry_run"])
                self.assertEqual(self.snapshot(p), before)
                self.assertEqual([n for n in os.listdir(self._tmp.name) if ".bak-" in n], [])

    def test_dry_run_create_and_convert(self):
        p = self.make("csv")
        q = self.path("new.xlsx")
        self.assertTrue(sheet("create", q, "--dry-run")["dry_run"])
        self.assertFalse(os.path.exists(q))
        self.assertTrue(sheet("convert", p, q, "--dry-run")["dry_run"])
        self.assertFalse(os.path.exists(q))

    def test_backup(self):
        for ext in FORMATS:
            with self.subTest(ext):
                p = self.make(ext)
                before = self.snapshot(p)
                out = sheet("write", p, "--cell", "A1", "--value", "zzz", "--backup")
                bak = out["backup"]
                self.assertRegex(os.path.basename(bak), r"^t\.%s\.bak-\d{8}T\d{6}Z$" % ext)
                self.assertEqual(os.path.dirname(bak), os.path.dirname(p))
                self.assertEqual(self.snapshot(bak), before)
                self.assertEqual(self.values(p)[0][0], "zzz")
                os.remove(bak)

    def test_backup_batch_convert_and_dry_run_combo(self):
        p = self.make("xlsx")
        out = sheet("batch", p, "--ops", json.dumps([{"action": "write", "cell": "A1", "value": "q"}]), "--backup")
        self.assertTrue(os.path.exists(out["backup"]))
        q = self.make("ods")
        r = self.path("dst.csv")
        sheet("convert", q, r)
        self.assertTrue(os.path.exists(sheet("convert", q, r, "--backup")["backup"]))
        out = sheet("write", p, "--cell", "A1", "--value", "w", "--backup", "--dry-run")
        self.assertNotIn("backup", out)


class Limits(Base):
    def test_size_limit(self):
        p = self.path("big.csv")
        with open(p, "wb") as f:
            f.truncate(51 * 1024 * 1024)
        self.assertIn("too large", self.err("info", p))

    def test_garbage_files_give_json_errors(self):
        for ext in ("xlsx", "ods"):
            p = self.path(f"bad.{ext}")
            with open(p, "wb") as f:
                f.write(b"not a zip")
            self.assertIn(f"cannot read {ext}", self.err("info", p))
        self.assertNoLockFiles()


class Daemon(Base):
    def test_start_reuse_stop(self):
        sheet("stop")
        self.assertFalse(sheet("status")["running"])
        p = self.make("csv")
        first = sheet("status")
        self.assertTrue(first["running"])
        sheet("info", p)
        self.assertEqual(sheet("status")["pid"], first["pid"])
        self.assertTrue(sheet("stop")["stopped"])
        self.assertEqual(sheet("status"), {"ok": True, "running": False, "pid": None, "idle_seconds": None})
        self.assertFalse(sheet("stop")["stopped"])
        sheet("info", p)
        self.assertTrue(sheet("status")["running"])
        self.assertNotEqual(sheet("status")["pid"], first["pid"])

    def test_recovers_from_killed_daemon(self):
        import signal
        p = self.make("csv")
        os.killpg(sheet("status")["pid"], signal.SIGKILL)
        time.sleep(0.5)
        self.assertEqual(sheet("info", p)["format"], "csv")

    def test_idle_watchdog_stops_daemon(self):
        sheet("stop")
        os.environ["SHEETCLI_IDLE_SECONDS"] = "2"
        try:
            self.make("csv")
        finally:
            del os.environ["SHEETCLI_IDLE_SECONDS"]
        deadline = time.time() + 30
        while time.time() < deadline and sheet("status")["running"]:
            time.sleep(0.5)
        self.assertFalse(sheet("status")["running"])

    def test_serialized_parallel_calls(self):
        p = self.make("csv", data='[["n"]]')
        env = {**os.environ}
        script = os.path.join(ROOT, "src", "sheet.py")
        procs = [subprocess.Popen([sys.executable, script, "append", p, "--data", f'[[{i}]]'],
                                  env=env, stdout=subprocess.PIPE, text=True) for i in range(4)]
        for pr in procs:
            self.assertTrue(json.loads(pr.communicate()[0])["ok"])
        self.assertEqual(sorted(r[0] for r in self.values(p)[1:]), [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
