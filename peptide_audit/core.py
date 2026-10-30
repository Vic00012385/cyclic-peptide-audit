"""Validate candidate CSVs and summarize observed computational screening results.

Rates always use all generated candidates in the corresponding group as their
denominator. These summaries describe the supplied data, not binding affinity.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

__all__ = ["load_candidates", "analyze"]

REQUIRED_COLUMNS = (
    "candidate_id",
    "target",
    "topology",
    "pre_closure",
    "post_closure",
    "ddg",
    "sap",
    "cms",
)
_BOOLEAN_COLUMNS = ("pre_closure", "post_closure")
_NUMERIC_COLUMNS = ("ddg", "sap", "cms")
_TRUE_VALUES = {"true", "1", "yes"}
_FALSE_VALUES = {"false", "0", "no"}


def _row_error(line_number: int, message: str) -> ValueError:
    return ValueError(f"CSV line {line_number}: {message}")


def load_candidates(path: str | Path) -> list[dict[str, Any]]:
    """Read a UTF-8 CSV, returning stripped strings, booleans and finite floats.

    A UTF-8 byte order mark is accepted. Extra named columns are preserved as
    stripped strings. Candidate IDs must be unique within each target, including
    across topologies. Invalid content raises ``ValueError`` with a physical CSV
    line number; filesystem errors retain their usual ``OSError`` types.
    """
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    with open(path, encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        try:
            header = reader.fieldnames
            if header is None:
                raise _row_error(1, "empty file; expected a header and data rows")
            header = [name.strip() for name in header]
            reader.fieldnames = header
            if any(not name for name in header):
                raise _row_error(1, "column names must not be empty")
            if len(set(header)) != len(header):
                raise _row_error(1, "duplicate column names")
            missing = [name for name in REQUIRED_COLUMNS if name not in header]
            if missing:
                raise _row_error(1, "missing required columns: " + ", ".join(missing))

            for raw in reader:
                line_number = reader.line_num
                if None in raw:
                    raise _row_error(line_number, "row has more fields than the header")
                if any(value is None for value in raw.values()):
                    raise _row_error(line_number, "row has fewer fields than the header")
                candidate: dict[str, Any] = {
                    name: value.strip() for name, value in raw.items()
                }
                for name in REQUIRED_COLUMNS:
                    if candidate[name] == "":
                        raise _row_error(line_number, f"{name} must not be empty")
                for name in _BOOLEAN_COLUMNS:
                    value = candidate[name].lower()
                    if value in _TRUE_VALUES:
                        candidate[name] = True
                    elif value in _FALSE_VALUES:
                        candidate[name] = False
                    else:
                        raise _row_error(
                            line_number,
                            f"{name} must be true/false, 1/0 or yes/no",
                        )
                for name in _NUMERIC_COLUMNS:
                    try:
                        value = float(candidate[name])
                    except (ValueError, OverflowError):
                        raise _row_error(line_number, f"{name} must be a finite number") from None
                    if not math.isfinite(value):
                        raise _row_error(line_number, f"{name} must be a finite number")
                    candidate[name] = value
                identity = (candidate["target"], candidate["candidate_id"])
                if identity in seen:
                    raise _row_error(
                        line_number,
                        f"duplicate candidate_id {identity[1]!r} within target {identity[0]!r}",
                    )
                seen.add(identity)
                candidates.append(candidate)
        except csv.Error as error:
            raise _row_error(max(reader.line_num, 1), str(error)) from error
    if not candidates:
        raise _row_error(max(reader.line_num, 1), "no data rows")
    return candidates


def _summarize(
    candidates: list[dict[str, Any]],
    ddg_max: float,
    sap_max: float,
    cms_min: float,
) -> dict[str, Any]:
    generated = len(candidates)
    pre_closed = post_closed = both_closed = joint_pass = 0
    relax_lost = relax_gained = 0
    failures = dict.fromkeys((*_BOOLEAN_COLUMNS, *_NUMERIC_COLUMNS), 0)
    for candidate in candidates:
        pre = candidate["pre_closure"]
        post = candidate["post_closure"]
        passed = {
            "pre_closure": pre,
            "post_closure": post,
            "ddg": candidate["ddg"] < ddg_max,
            "sap": candidate["sap"] < sap_max,
            "cms": candidate["cms"] > cms_min,
        }
        pre_closed += int(pre)
        post_closed += int(post)
        both_closed += int(pre and post)
        joint_pass += int(all(passed.values()))
        relax_lost += int(pre and not post)
        relax_gained += int(post and not pre)
        for name, did_pass in passed.items():
            failures[name] += int(not did_pass)
    return {
        "generated": generated,
        "pre_closed": pre_closed,
        "post_closed": post_closed,
        "both_closed": both_closed,
        "joint_pass": joint_pass,
        "pre_rate": pre_closed / generated if generated else 0.0,
        "post_rate": post_closed / generated if generated else 0.0,
        "joint_rate": joint_pass / generated if generated else 0.0,
        "relax_lost": relax_lost,
        "relax_gained": relax_gained,
        "mean_ddg": (
            math.fsum(candidate["ddg"] / generated for candidate in candidates)
            if generated
            else None
        ),
        "failures": failures,
    }


def analyze(
    candidates: list[dict[str, Any]],
    ddg_max: float = -35.0,
    sap_max: float = 35.0,
    cms_min: float = 300.0,
) -> dict[str, Any]:
    """Summarize parsed candidates using strict numeric threshold comparisons.

    ``joint_pass`` requires both closure flags and all three numeric conditions.
    Failure counts are independent and can overlap. ``mean_ddg`` includes every
    generated row, without filtering. Empty input yields zero counts/rates and
    a null mean. Input dictionaries are not modified.
    """
    thresholds = {"ddg_max": ddg_max, "sap_max": sap_max, "cms_min": cms_min}
    for name, value in thresholds.items():
        try:
            thresholds[name] = float(value)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"{name} must be a finite number") from None
        if not math.isfinite(thresholds[name]):
            raise ValueError(f"{name} must be a finite number")
    by_group: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_group[(candidate["target"], candidate["topology"])].append(candidate)
    return {
        "schema_version": "1.0",
        "thresholds": thresholds,
        "summary": _summarize(candidates, **thresholds),
        "groups": [
            {"target": target, "topology": topology, **_summarize(rows, **thresholds)}
            for (target, topology), rows in sorted(by_group.items())
        ],
    }
