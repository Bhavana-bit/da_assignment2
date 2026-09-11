#!/usr/bin/env python3
"""Inspect M26_DA_A2_Part2.csv without loading the full dataset into memory."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


MISSING_MARKERS = {"", "?", "NA", "N/A", "null", "NULL"}
TARGET_CANDIDATES = {"income"}
WEIGHT_CANDIDATES = {"instance_weight"}
CODE_NAME_RE = re.compile(r"(?:^|_)(?:code|id)(?:_|$)")
NUMERIC_NAME_RE = re.compile(
    r"(?:^|_)(?:age|wage|gains|losses|dividends|weight|persons|members|weeks|year)(?:_|$)"
)


def parse_value(raw: str) -> tuple[str, Any]:
    """Return missing, integer, float, or string classification for one value."""
    value = raw.strip()
    if value in MISSING_MARKERS:
        return "missing", None
    try:
        integer = int(value)
    except ValueError:
        try:
            number = float(value)
        except ValueError:
            return "string", value
        return "float", number
    return "integer", integer


def inferred_type(stats: dict[str, Any]) -> str:
    observed = stats["observed_types"]
    if not observed:
        return "empty"
    if observed <= {"integer"}:
        return "integer"
    if observed <= {"integer", "float"}:
        return "numeric"
    if "string" in observed and len(observed) > 1:
        return "mixed"
    return "string"


def is_code_dimension(name: str) -> bool:
    return bool(CODE_NAME_RE.search(name))


def should_recommend_dimension(name: str, stats: dict[str, Any], target: str, weight: str) -> tuple[bool, str]:
    if name in {target, weight}:
        return False, "excluded target/weight"
    kind = stats["inferred_type"]
    if kind in {"string", "mixed"}:
        return True, "categorical text"
    if is_code_dimension(name):
        return True, "coded category; numeric values are labels"
    return False, "numeric measure or continuous attribute"


def detect_hierarchy_pairs(columns: list[str]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    candidates = [
        ("industry_code_detailed", "industry_code_major", "industry"),
        ("occupation_code_detailed", "occupation_code_major", "occupation"),
        ("household_family_status", "household_summary", "household"),
        ("state_prev_residence", "region_prev_residence", "state/region of previous residence"),
    ]
    available = set(columns)
    for detailed, summary, subject in candidates:
        if detailed in available and summary in available:
            pairs.append({"subject": subject, "detailed": detailed, "summary": summary})
    return pairs


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value)


def inspect_dataset(path: Path) -> dict[str, Any]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            columns = next(reader)
        except StopIteration as exc:
            raise ValueError("The CSV is empty and has no header.") from exc

        stats = {
            column: {
                "missing": 0,
                "observed_types": set(),
                "counter": Counter(),
                "minimum": None,
                "maximum": None,
            }
            for column in columns
        }
        row_count = 0
        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(columns):
                raise ValueError(
                    f"Row {row_number} has {len(row)} fields; expected {len(columns)}."
                )
            row_count += 1
            for column, raw in zip(columns, row):
                column_stats = stats[column]
                value_type, value = parse_value(raw)
                if value_type == "missing":
                    column_stats["missing"] += 1
                    continue
                column_stats["observed_types"].add(value_type)
                column_stats["counter"][str(value)] += 1
                if value_type in {"integer", "float"}:
                    if column_stats["minimum"] is None or value < column_stats["minimum"]:
                        column_stats["minimum"] = value
                    if column_stats["maximum"] is None or value > column_stats["maximum"]:
                        column_stats["maximum"] = value

    for column in columns:
        stats[column]["inferred_type"] = inferred_type(stats[column])

    target = next((name for name in columns if name in TARGET_CANDIDATES), None)
    weight = next((name for name in columns if name in WEIGHT_CANDIDATES), None)
    for column in columns:
        recommended, reason = should_recommend_dimension(column, stats[column], target or "", weight or "")
        stats[column]["recommended_dimension"] = recommended
        stats[column]["dimension_reason"] = reason

    numeric_attributes = [
        column
        for column in columns
        if stats[column]["inferred_type"] in {"integer", "numeric"}
        and column not in {target, weight}
        and not is_code_dimension(column)
    ]
    numeric_code_dimensions = [
        column
        for column in columns
        if stats[column]["inferred_type"] in {"integer", "numeric"}
        and stats[column]["recommended_dimension"]
    ]
    dimensions = [column for column in columns if stats[column]["recommended_dimension"]]
    return {
        "file": str(path),
        "rows": row_count,
        "columns": len(columns),
        "column_names": columns,
        "target_column": target,
        "instance_weight_column": weight,
        "recommended_cube_dimensions": dimensions,
        "numeric_attributes_not_dimensions": numeric_attributes,
        "numeric_code_dimensions": numeric_code_dimensions,
        "hierarchy_pairs": detect_hierarchy_pairs(columns),
        "columns_detail": [
            {
                "column": column,
                "data_type": stats[column]["inferred_type"],
                "unique_values": len(stats[column]["counter"]),
                "missing_values": stats[column]["missing"],
                "missing_percent": round(stats[column]["missing"] * 100 / row_count, 4)
                if row_count
                else 0.0,
                "most_common_values": [
                    {"value": value, "frequency": frequency}
                    for value, frequency in stats[column]["counter"].most_common(10)
                ],
                "minimum": format_value(stats[column]["minimum"]),
                "maximum": format_value(stats[column]["maximum"]),
                "recommended_cube_dimension": stats[column]["recommended_dimension"],
                "dimension_reason": stats[column]["dimension_reason"],
            }
            for column in columns
        ],
    }


def write_outputs(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "dataset_inspection.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    with (output_dir / "dataset_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "column", "data_type", "unique_values", "missing_values", "missing_percent",
            "minimum", "maximum", "recommended_cube_dimension", "dimension_reason",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            {key: detail[key] for key in fieldnames} for detail in result["columns_detail"]
        )

    lines = [
        "# M26_DA_A2 Part II Dataset Inspection",
        "",
        f"- **File:** `{result['file']}`",
        f"- **Rows:** {result['rows']:,}",
        f"- **Columns:** {result['columns']}",
        f"- **Target column:** `{result['target_column']}`",
        f"- **Instance-weight column:** `{result['instance_weight_column']}` (excluded from cube dimensions)",
        "",
        "## All Column Names",
        "",
        ", ".join(f"`{name}`" for name in result["column_names"]),
        "",
        "## Recommended Cube Dimensions",
        "",
        f"{len(result['recommended_cube_dimensions'])} dimensions: "
        + ", ".join(f"`{name}`" for name in result["recommended_cube_dimensions"]),
        "",
        "## Numeric Attributes Not Recommended As Dimensions",
        "",
        ", ".join(f"`{name}`" for name in result["numeric_attributes_not_dimensions"]),
        "",
        "Numeric-coded dimensions retained because their values are category labels: "
        + ", ".join(f"`{name}`" for name in result["numeric_code_dimensions"])
        + ".",
        "",
        "## Detected Hierarchy Pairs",
        "",
        "| Subject | Detailed level | Summary level |",
        "|---|---|---|",
    ]
    for pair in result["hierarchy_pairs"]:
        lines.append(f"| {pair['subject']} | `{pair['detailed']}` | `{pair['summary']}` |")
    lines.extend([
        "",
        "## Column Summary",
        "",
        "| Column | Type | Unique | Missing | Min | Max | Cube dimension |",
        "|---|---:|---:|---:|---:|---:|---|",
    ])
    for detail in result["columns_detail"]:
        lines.append(
            f"| `{detail['column']}` | {detail['data_type']} | {detail['unique_values']:,} | "
            f"{detail['missing_values']:,} ({detail['missing_percent']}%) | "
            f"{detail['minimum'] or '-'} | {detail['maximum'] or '-'} | "
            f"{'yes' if detail['recommended_cube_dimension'] else 'no'} |"
        )
    lines.extend(["", "## Most Common Values For Categorical Dimensions", ""])
    for detail in result["columns_detail"]:
        if detail["recommended_cube_dimension"]:
            common = ", ".join(
                f"{item['value']} ({item['frequency']:,})"
                for item in detail["most_common_values"]
            )
            lines.append(f"- `{detail['column']}`: {common}")
    (output_dir / "dataset_inspection_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", nargs="?", type=Path, default=Path("M26_DA_A2_Part2.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("dataset_inspection"))
    args = parser.parse_args()
    result = inspect_dataset(args.csv_path)
    write_outputs(result, args.output_dir)
    print(f"Rows: {result['rows']:,}")
    print(f"Columns: {result['columns']}")
    print("Columns:", ", ".join(result["column_names"]))
    print(f"Target: {result['target_column']}")
    print(f"Instance weight: {result['instance_weight_column']}")
    print(f"Recommended cube dimensions ({len(result['recommended_cube_dimensions'])}):")
    print("  " + ", ".join(result["recommended_cube_dimensions"]))
    print("Numeric attributes not recommended as dimensions:")
    print("  " + ", ".join(result["numeric_attributes_not_dimensions"]))
    print("Hierarchy pairs:")
    for pair in result["hierarchy_pairs"]:
        print(f"  {pair['detailed']} -> {pair['summary']} ({pair['subject']})")
    print(f"Reports written to: {args.output_dir}")


if __name__ == "__main__":
    main()