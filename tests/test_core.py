"""Meaningful core validation and screening-accounting tests (stdlib only)."""

import json
import tempfile
import unittest
from pathlib import Path

from peptide_audit.core import analyze, load_candidates


HEADER = "candidate_id,target,topology,pre_closure,post_closure,ddg,sap,cms"


class LoadCandidatesTests(unittest.TestCase):
    def load_text(self, content):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidates.csv"
            path.write_text(content, encoding="utf-8")
            return load_candidates(path)

    def test_values_are_stripped_and_parsed_and_extra_columns_preserved(self):
        rows = self.load_text(
            "\ufeff" + HEADER + ",note\n"
            " p1 , Target A , H2T , YeS , 0 , -40.5 , 12 , 321.5 , example \n"
        )
        self.assertEqual(rows, [{
            "candidate_id": "p1", "target": "Target A", "topology": "H2T",
            "pre_closure": True, "post_closure": False,
            "ddg": -40.5, "sap": 12.0, "cms": 321.5, "note": "example",
        }])

    def test_all_boolean_forms(self):
        for text, value in (("true", True), ("FALSE", False), ("1", True),
                            ("0", False), ("yes", True), ("No", False)):
            with self.subTest(text=text):
                rows = self.load_text(HEADER + f"\np1,T,A,{text},{text},-40,20,400\n")
                self.assertIs(rows[0]["pre_closure"], value)
                self.assertIs(rows[0]["post_closure"], value)

    def test_duplicate_id_rejected_with_line_number_even_across_topologies(self):
        with self.assertRaisesRegex(ValueError, r"line 3: duplicate candidate_id"):
            self.load_text(HEADER + "\np1,T,A,true,true,-40,20,400\np1,T,B,true,true,-40,20,400\n")

    def test_same_id_in_different_targets_is_valid(self):
        rows = self.load_text(HEADER + "\np1,T,A,true,true,-40,20,400\np1,U,A,true,true,-40,20,400\n")
        self.assertEqual(len(rows), 2)

    def test_empty_or_header_only_file_rejected(self):
        for text in ("", "\n\n", HEADER, HEADER + "\n\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, r"line \d+"):
                self.load_text(text)

    def test_missing_or_duplicate_columns_rejected(self):
        with self.assertRaisesRegex(ValueError, r"line 1: missing required columns: cms"):
            self.load_text(HEADER.rsplit(",", 1)[0] + "\np1,T,A,true,true,-40,20\n")
        with self.assertRaisesRegex(ValueError, r"line 1: duplicate column names"):
            self.load_text(HEADER + ",target\n")

    def test_empty_or_invalid_required_values_rejected(self):
        original = ["p1", "T", "A", "true", "true", "-40", "20", "400"]
        bad_values = [(index, " ") for index in range(8)]
        bad_values += [(3, "maybe"), (4, "2"), (5, "bad"), (6, "nan"), (7, "inf")]
        bad_values += [(index, value) for index in (5, 6, 7) for value in ("NaN", "-inf", "1e999")]
        for index, bad in bad_values:
            row = original.copy()
            row[index] = bad
            with self.subTest(index=index, bad=bad), self.assertRaisesRegex(ValueError, r"line 2:"):
                self.load_text(HEADER + "\n" + ",".join(row) + "\n")

    def test_wrong_number_of_fields_rejected(self):
        for row in ("p1,T,A,true,true,-40,20", "p1,T,A,true,true,-40,20,400,extra"):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, r"line 2:"):
                self.load_text(HEADER + "\n" + row + "\n")

    def test_malformed_quoted_csv_rejected(self):
        with self.assertRaisesRegex(ValueError, r"line \d+:"):
            self.load_text(HEADER + '\np1,T,"unterminated,true,true,-40,20,400\n')


def candidate(identifier, target="T", topology="A", pre=True, post=True,
              ddg=-40.0, sap=20.0, cms=400.0):
    return {"candidate_id": identifier, "target": target, "topology": topology,
            "pre_closure": pre, "post_closure": post, "ddg": ddg,
            "sap": sap, "cms": cms}


class AnalyzeTests(unittest.TestCase):
    def test_counts_use_all_generated_rows_and_track_relaxation_transitions(self):
        report = analyze([
            candidate("pass"),
            candidate("lost", pre=True, post=False),
            candidate("gained", pre=False, post=True),
            candidate("neither", pre=False, post=False),
        ])
        summary = report["summary"]
        self.assertEqual(summary["generated"], 4)
        self.assertEqual(summary["pre_closed"], 2)
        self.assertEqual(summary["post_closed"], 2)
        self.assertEqual(summary["both_closed"], 1)
        self.assertEqual(summary["joint_pass"], 1)
        self.assertEqual(summary["pre_rate"], .5)
        self.assertEqual(summary["post_rate"], .5)
        self.assertEqual(summary["joint_rate"], .25)
        self.assertEqual(summary["relax_lost"], 1)
        self.assertEqual(summary["relax_gained"], 1)
        self.assertEqual(summary["failures"], {
            "pre_closure": 2, "post_closure": 2, "ddg": 0, "sap": 0, "cms": 0,
        })

    def test_thresholds_are_strict_and_failures_overlap(self):
        report = analyze([
            candidate("all-boundaries", ddg=-35, sap=35, cms=300),
            candidate("ddg-boundary", ddg=-35),
            candidate("sap-boundary", sap=35),
            candidate("cms-boundary", cms=300),
            candidate("passes"),
        ])
        self.assertEqual(report["summary"]["joint_pass"], 1)
        self.assertEqual(report["summary"]["joint_rate"], .2)
        self.assertEqual(report["summary"]["failures"], {
            "pre_closure": 0, "post_closure": 0, "ddg": 2, "sap": 2, "cms": 2,
        })

    def test_custom_thresholds_are_recorded_and_applied(self):
        report = analyze([candidate("p1", ddg=-30, sap=30, cms=250)], -25, 31, 240)
        self.assertEqual(report["thresholds"], {"ddg_max": -25., "sap_max": 31., "cms_min": 240.})
        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["summary"]["joint_pass"], 1)

    def test_groups_are_sorted_and_summary_is_weighted_by_candidates(self):
        rows = [candidate("p1", target="Z", ddg=-60),
                candidate("p2", target="A", topology="B", ddg=-20),
                candidate("p3", target="A", topology="A", ddg=-30),
                candidate("p4", target="A", topology="A", ddg=-10)]
        report = analyze(rows)
        self.assertEqual([(g["target"], g["topology"]) for g in report["groups"]],
                         [("A", "A"), ("A", "B"), ("Z", "A")])
        self.assertEqual(report["summary"]["mean_ddg"], -30.)
        self.assertEqual(report["groups"][0]["mean_ddg"], -20.)
        self.assertEqual(report["groups"][0]["generated"], 2)
        for key in ("generated", "pre_closed", "post_closed", "both_closed", "joint_pass",
                    "relax_lost", "relax_gained"):
            self.assertEqual(report["summary"][key], sum(group[key] for group in report["groups"]))

    def test_empty_analysis_is_json_serializable_and_has_defined_rates(self):
        report = analyze([])
        self.assertEqual(report["groups"], [])
        self.assertEqual(report["summary"]["generated"], 0)
        self.assertEqual(report["summary"]["joint_rate"], 0.)
        self.assertIsNone(report["summary"]["mean_ddg"])
        json.dumps(report, allow_nan=False)

    def test_nonfinite_thresholds_rejected(self):
        for name in ("ddg_max", "sap_max", "cms_min"):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, name):
                    analyze([], **{name: value})

    def test_analysis_does_not_mutate_input(self):
        rows = [candidate("p1")]
        before = [row.copy() for row in rows]
        json.dumps(analyze(rows), allow_nan=False)
        self.assertEqual(rows, before)


if __name__ == "__main__":
    unittest.main()
