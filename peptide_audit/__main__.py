"""Run with: python -m peptide_audit candidates.csv --out report."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .core import analyze, load_candidates
from .report import render_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit observed closure and screening outcomes by target and topology."
    )
    parser.add_argument("input", type=Path, help="UTF-8 candidate CSV")
    parser.add_argument("--out", type=Path, default=Path("report"), help="Output directory")
    parser.add_argument("--ddg-max", type=float, default=-35.0)
    parser.add_argument("--sap-max", type=float, default=35.0)
    parser.add_argument("--cms-min", type=float, default=300.0)
    parser.add_argument("--demo", action="store_true", help="Label the report as synthetic demo data")
    parser.add_argument("--force", action="store_true", help="Replace existing report files")
    args = parser.parse_args(argv)
    try:
        candidates = load_candidates(args.input)
        result = analyze(candidates, args.ddg_max, args.sap_max, args.cms_min)
        result["source"] = args.input.name
        result["synthetic_demo"] = args.demo
        output_files = [args.out / name for name in ("index.html", "summary.csv", "audit.json")]
        if args.input.resolve() in [path.resolve() for path in output_files]:
            raise ValueError("output would overwrite the input CSV; choose another --out directory")
        existing = [path.name for path in output_files if path.exists()]
        if existing and not args.force:
            raise ValueError("report files already exist: " + ", ".join(existing)
                             + "; choose another --out directory or use --force")
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "audit.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        fields = ["target", "topology", "generated", "pre_closed", "post_closed", "both_closed",
                  "joint_pass", "pre_rate", "post_rate", "joint_rate", "relax_lost", "relax_gained",
                  "mean_ddg", "fail_pre_closure", "fail_post_closure", "fail_ddg", "fail_sap", "fail_cms"]
        with (args.out / "summary.csv").open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=fields)
            writer.writeheader()
            for group in result["groups"]:
                row = {name: group[name] for name in fields if name in group}
                row.update({f"fail_{name}": count for name, count in group["failures"].items()})
                writer.writerow(row)
        (args.out / "index.html").write_text(render_report(result), encoding="utf-8")
    except (ValueError, OSError, UnicodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    totals = result["summary"]
    print(f"Audited {totals['generated']} candidates across {len(result['groups'])} groups.")
    print(f"Joint pass: {totals['joint_pass']}/{totals['generated']} ({totals['joint_rate']:.1%}).")
    print(f"Report: {args.out / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
