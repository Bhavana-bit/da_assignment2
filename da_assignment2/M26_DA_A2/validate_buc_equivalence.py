#!/usr/bin/env python3
"""Rigorous equivalence test for in-memory and paged BUC."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from buc import buc
from buc_out_of_memory import buc_out_of_memory


SELECTED_DIMENSIONS = [
    "sex",
    "race",
    "marital_status",
    "tax_filer_status",
    "employment_status",
    "class_of_worker",
    "education",
    "industry_code_major",
    "occupation_code_major",
    "household_summary",
    "region_prev_residence",
    "state_prev_residence",
]


def load_logical_input(
    csv_path: Path, dimensions: list[str], sample_size: int | None
) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        records = []
        for record in reader:
            records.append({dimension: record[dimension] for dimension in dimensions})
            if sample_size is not None and len(records) >= sample_size:
                break
    return records


def canonical_cells(
    cells: list[dict[str, Any]] | tuple[dict[str, Any], ...], dimensions: list[str]
) -> dict[tuple[tuple[str, Any], ...], int]:
    canonical: dict[tuple[tuple[str, Any], ...], int] = {}
    for cell in cells:
        key_order = tuple(cell["dimensions"])
        if key_order != tuple(dimensions):
            raise AssertionError(f"Unexpected dimension order: {key_order}")
        key = tuple(cell["dimensions"].items())
        if key in canonical:
            raise AssertionError(f"Duplicate canonical cube cell: {key}")
        canonical[key] = int(cell["measure"])
    return canonical


def compare_one(
    records: list[dict[str, str]], dimensions: list[str], minsup: int, memory_limit_rows: int
) -> dict[str, Any]:
    in_memory = canonical_cells(buc(records, dimensions, measure="count", minsup=minsup), dimensions)
    paged_result = buc_out_of_memory(
        records,
        dimensions,
        measure="count",
        minsup=minsup,
        memory_limit_rows=memory_limit_rows,
    )
    paged = canonical_cells(paged_result.cells, dimensions)
    in_memory_keys = set(in_memory)
    paged_keys = set(paged)
    only_in_memory = in_memory_keys - paged_keys
    only_in_paged = paged_keys - in_memory_keys
    common = in_memory_keys & paged_keys
    support_mismatches = {
        key: {"in_memory": in_memory[key], "paged": paged[key]}
        for key in common
        if in_memory[key] != paged[key]
    }
    mismatch_differences = [abs(values["in_memory"] - values["paged"]) for values in support_mismatches.values()]
    passed = not only_in_memory and not only_in_paged and not support_mismatches
    return {
        "passed": passed,
        "minsup": minsup,
        "memory_limit_rows": memory_limit_rows,
        "in_memory_cells": len(in_memory),
        "paged_cells": len(paged),
        "dimension_combinations_only_in_memory": len(only_in_memory),
        "dimension_combinations_only_in_paged": len(only_in_paged),
        "support_mismatches": len(support_mismatches),
        "maximum_absolute_support_difference": max(mismatch_differences, default=0),
        "first_only_in_memory": _example(only_in_memory, in_memory),
        "first_only_in_paged": _example(only_in_paged, paged),
        "first_support_mismatch": _example_mismatch(support_mismatches),
        "paged_runtime_seconds": paged_result.elapsed_seconds,
        "estimated_peak_buffer_rows": paged_result.metrics.estimated_peak_buffer_rows,
        "partitions_spilled": paged_result.metrics.partitions_spilled,
        "bytes_spilled": paged_result.metrics.bytes_spilled,
        "pages_processed": paged_result.metrics.pages_processed,
    }


def _example(keys: set[tuple[tuple[str, Any], ...]], cells: dict) -> dict[str, Any] | None:
    if not keys:
        return None
    key = sorted(keys, key=repr)[0]
    return {"dimensions": dict(key), "support": cells[key]}


def _example_mismatch(mismatches: dict) -> dict[str, Any] | None:
    if not mismatches:
        return None
    key = sorted(mismatches, key=repr)[0]
    return {"dimensions": dict(key), **mismatches[key]}


def print_report(csv_path: Path, records: list[dict[str, str]], reports: list[dict[str, Any]]) -> bool:
    all_passed = all(report["passed"] for report in reports)
    print(f"Equivalence test: {'PASS' if all_passed else 'FAIL'}")
    print(f"Input: {csv_path}")
    print(f"Rows in same logical input: {len(records):,}")
    print(f"Dimensions ({len(SELECTED_DIMENSIONS)}): {', '.join(SELECTED_DIMENSIONS)}")
    print(f"Runs: {len(reports)}")
    for report in reports:
        status = "PASS" if report["passed"] else "FAIL"
        print(
            f"[{status}] minsup={report['minsup']} memory_limit_rows={report['memory_limit_rows']} "
            f"in_memory_cells={report['in_memory_cells']} paged_cells={report['paged_cells']} "
            f"only_in_memory={report['dimension_combinations_only_in_memory']} "
            f"only_in_paged={report['dimension_combinations_only_in_paged']} "
            f"support_mismatches={report['support_mismatches']} "
            f"max_abs_support_difference={report['maximum_absolute_support_difference']}"
        )
        print(
            f"      paged_runtime={report['paged_runtime_seconds']:.6f}s "
            f"peak_estimated_rows={report['estimated_peak_buffer_rows']} "
            f"spilled_partitions={report['partitions_spilled']} "
            f"bytes_spilled={report['bytes_spilled']} pages={report['pages_processed']}"
        )
        if not report["passed"]:
            print(f"      first_only_in_memory={report['first_only_in_memory']}")
            print(f"      first_only_in_paged={report['first_only_in_paged']}")
            print(f"      first_support_mismatch={report['first_support_mismatch']}")
    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, default=Path("M26_DA_A2_Part2.csv"), nargs="?")
    parser.add_argument("--sample-size", type=int, default=250)
    parser.add_argument("--minsup", type=int, nargs="+", default=[25, 50, 100])
    parser.add_argument("--memory-limit-rows", type=int, nargs="+", default=[1, 7, 25, 100])
    parser.add_argument("--full", action="store_true", help="Use all CSV rows instead of a sample")
    args = parser.parse_args()
    if not args.full and args.sample_size < 1:
        parser.error("--sample-size must be positive")
    if any(value < 1 for value in args.minsup + args.memory_limit_rows):
        parser.error("minsup and memory limits must be positive")

    sample_size = None if args.full else args.sample_size
    records = load_logical_input(args.csv_path, SELECTED_DIMENSIONS, sample_size)
    reports = [
        compare_one(records, SELECTED_DIMENSIONS, minsup, memory_limit_rows)
        for minsup in args.minsup
        for memory_limit_rows in args.memory_limit_rows
    ]
    return 0 if print_report(args.csv_path, records, reports) else 1


if __name__ == "__main__":
    sys.exit(main())
