#!/usr/bin/env python3
"""Validate BUC against an independent reference aggregation.

The reference implementation is intentionally separate from BUC: it enumerates
subsets of dimensions and counts tuple keys directly. It is suitable for small
validation inputs, not for production cube computation.
"""

from __future__ import annotations

import argparse
import csv
import itertools
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from buc import ALL, buc


def reference_cube(
    records: Sequence[Mapping[str, Any]], dimensions: Sequence[str], minsup: int
) -> list[dict[str, Any]]:
    """Build a complete reference cube by direct subset aggregation."""
    output: list[dict[str, Any]] = []
    for selected_count in range(len(dimensions) + 1):
        for selected_dimensions in itertools.combinations(dimensions, selected_count):
            counts = Counter(
                tuple(record[dimension] for dimension in selected_dimensions)
                for record in records
            )
            for selected_values, support in sorted(counts.items(), key=lambda item: repr(item[0])):
                if support < minsup:
                    continue
                selected = dict(zip(selected_dimensions, selected_values))
                output.append({
                    "dimensions": {
                        dimension: selected.get(dimension, ALL) for dimension in dimensions
                    },
                    "measure": support,
                })
    return output


def normalize(cells: Iterable[dict[str, Any]], dimensions: Sequence[str]) -> set[tuple[tuple[tuple[str, Any], ...], int]]:
    """Normalize output for order-independent comparison while checking key order."""
    normalized = set()
    for cell in cells:
        keys = tuple(cell["dimensions"])
        if keys != tuple(dimensions):
            raise AssertionError(f"Dimension order changed: {keys!r} != {tuple(dimensions)!r}")
        normalized.add((tuple(cell["dimensions"].items()), cell["measure"]))
    return normalized


def compare(records: Sequence[Mapping[str, Any]], dimensions: Sequence[str], minsup: int) -> tuple[int, int]:
    expected = reference_cube(records, dimensions, minsup)
    actual = buc(records, dimensions, measure="count", minsup=minsup)
    expected_set = normalize(expected, dimensions)
    actual_set = normalize(actual, dimensions)
    if expected_set != actual_set:
        missing = expected_set - actual_set
        extra = actual_set - expected_set
        raise AssertionError(f"BUC mismatch: missing={list(missing)[:3]}, extra={list(extra)[:3]}")
    return len(expected), len(actual)


def synthetic_records() -> list[dict[str, str]]:
    return [
        {"region": "East", "sex": "F", "tier": "A"},
        {"region": "East", "sex": "M", "tier": "A"},
        {"region": "West", "sex": "M", "tier": "A"},
        {"region": "West", "sex": "M", "tier": "B"},
        {"region": "West", "sex": "F", "tier": "B"},
    ]


def load_sample(path: Path, dimensions: Sequence[str], sample_size: int) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(itertools.islice(csv.DictReader(handle), sample_size))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, default=Path("M26_DA_A2_Part2.csv"), nargs="?")
    parser.add_argument("--sample-size", type=int, default=2000)
    parser.add_argument("--minsup", type=int, default=50)
    args = parser.parse_args()

    synthetic_dimensions = ["region", "sex", "tier"]
    synthetic_expected, synthetic_actual = compare(synthetic_records(), synthetic_dimensions, 2)
    print(f"Synthetic validation passed: reference={synthetic_expected}, BUC={synthetic_actual}")

    sample_dimensions = ["sex", "race", "education", "industry_code_major"]
    sample = load_sample(args.csv_path, sample_dimensions, args.sample_size)
    sample_expected, sample_actual = compare(sample, sample_dimensions, args.minsup)
    print(
        f"CSV sample validation passed: rows={len(sample)}, dimensions={len(sample_dimensions)}, "
        f"minsup={args.minsup}, reference={sample_expected}, BUC={sample_actual}"
    )


if __name__ == "__main__":
    main()
