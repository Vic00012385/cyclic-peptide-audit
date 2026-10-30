"""Integration checks for exports, invalid inputs and safe replacement."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from peptide_audit.__main__ import main


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "input.csv"
        self.input.write_text(
            'candidate_id,target,topology,pre_closure,post_closure,ddg,sap,cms\n'
            'id1,<script>alert(1)</script>,Test,true,true,-40,20,400\n', encoding="utf-8"
        )
        self.out = self.root / "report"

    def run_cli(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main([str(self.input), "--out", str(self.out), *extra])

    def test_exports_valid_json_csv_and_html_with_safe_labels(self):
        self.assertEqual(self.run_cli("--demo"), 0)
        result = json.loads((self.out / "audit.json").read_text())
        self.assertEqual(result["summary"]["joint_pass"], 1)
        self.assertTrue(result["synthetic_demo"])
        self.assertTrue((self.out / "summary.csv").exists())
        report = (self.out / "index.html").read_text()
        self.assertNotIn("<script>alert(1)</script>", report)
        self.assertIn(r"\u003cscript\u003e", report)

    def test_existing_files_are_not_replaced_without_force(self):
        self.out.mkdir()
        page = self.out / "index.html"
        page.write_text("existing content")
        self.assertEqual(self.run_cli(), 2)
        self.assertEqual(page.read_text(), "existing content")
        self.assertEqual(self.run_cli("--force"), 0)
        self.assertIn("Ring Audit", page.read_text())

    def test_invalid_threshold_does_not_create_output(self):
        self.assertEqual(self.run_cli("--ddg-max", "nan"), 2)
        self.assertFalse(self.out.exists())

    def test_input_cannot_be_replaced_even_with_force(self):
        self.out.mkdir()
        self.input = self.out / "summary.csv"
        original = 'candidate_id,target,topology,pre_closure,post_closure,ddg,sap,cms\nid1,A,T,true,true,-40,20,400\n'
        self.input.write_text(original)
        self.assertEqual(self.run_cli("--force"), 2)
        self.assertEqual(self.input.read_text(), original)


if __name__ == "__main__":
    unittest.main()
