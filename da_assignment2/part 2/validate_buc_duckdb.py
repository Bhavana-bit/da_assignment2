#!/usr/bin/env python3
"""Validate in-memory BUC against DuckDB GROUP BY CUBE.

DuckDB is deliberately isolated to this module as an independent reference.
It is never imported or called by buc.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import duckdb

from buc import ALL, buc


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


def _cell_key(values: tuple[Any, ...], dimensions: list[str]) -> tuple[tuple[str, Any], ...]:
    return tuple(
        (dimension, ALL if value is None else value)
        for dimension, value in zip(dimensions, values)
    )


def duckdb_cube(
    csv_path: Path,
    dimensions: list[str],
    minsup: int,
    sample_size: int | None = None,
) -> dict[tuple[tuple[str, Any], ...], int]:
    """Run the independent DuckDB GROUP BY CUBE reference query."""
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET threads=1")
        connection.execute("SET preserve_insertion_order=false")
        csv_literal = str(csv_path).replace("'", "''")
        connection.execute(
            f"CREATE OR REPLACE VIEW source_data AS "
            f"SELECT * FROM read_csv_auto('{csv_literal}', header=true)"
        )
        source = "source_data"
        if sample_size is not None:
            source = f"(SELECT * FROM source_data LIMIT {sample_size}) AS sample_data"
        quoted_dimensions = ", ".join('"' + dimension.replace('"', '""') + '"' for dimension in dimensions)
        query = f"""
            SELECT {quoted_dimensions}, COUNT(*) AS support
            FROM {source}
            GROUP BY CUBE ({quoted_dimensions})
            HAVING COUNT(*) >= ?
        """
        rows = connection.execute(query, [minsup]).fetchall()
        return {
            _cell_key(tuple(row[:-1]), dimensions): int(row[-1])
            for row in rows
        }
    finally:
        connection.close()


def load_records(
    csv_path: Path, dimensions: list[str], sample_size: int | None = None
) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        records = []
        for record in reader:
            records.append({dimension: record[dimension] for dimension in dimensions})
            if sample_size is not None and len(records) >= sample_size:
                break
    return records


def buc_cube(
    records: list[dict[str, str]], dimensions: list[str], minsup: int
) -> dict[tuple[tuple[str, Any], ...], int]:
    return {
        tuple(cell["dimensions"].items()): int(cell["measure"])
        for cell in buc(records, dimensions, measure="count", minsup=minsup)
    }


def compare_cubes(
    buc_cells: dict[tuple[tuple[str, Any], ...], int],
    duckdb_cells: dict[tuple[tuple[str, Any], ...], int],
) -> dict[str, Any]:
    buc_keys = set(buc_cells)
    duckdb_keys = set(duckdb_cells)
    only_buc = buc_keys - duckdb_keys
    only_duckdb = duckdb_keys - buc_keys
    common = buc_keys & duckdb_keys
    mismatches = {
        key: {"buc": buc_cells[key], "duckdb": duckdb_cells[key]}
        for key in common
        if buc_cells[key] != duckdb_cells[key]
    }
    differences = [abs(buc_cells[key] - duckdb_cells[key]) for key in common]
    return {
        "number_buc_cells": len(buc_cells),
        "number_duckdb_cells": len(duckdb_cells),
        "cells_only_in_buc": len(only_buc),
        "cells_only_in_duckdb": len(only_duckdb),
        "support_mismatches": len(mismatches),
        "maximum_absolute_support_difference": max(differences, default=0),
        "only_in_buc_examples": [
            {"dimensions": dict(key), "support": buc_cells[key]}
            for key in sorted(only_buc, key=repr)[:5]
        ],
        "only_in_duckdb_examples": [
            {"dimensions": dict(key), "support": duckdb_cells[key]}
            for key in sorted(only_duckdb, key=repr)[:5]
        ],
        "support_mismatch_examples": [
            {"dimensions": dict(key), **values}
            for key, values in sorted(mismatches.items(), key=repr)[:5]
        ],
    }


def validate(
    csv_path: Path,
    dimensions: list[str],
    minsup: int,
    sample_size: int | None,
) -> dict[str, Any]:
    start = time.perf_counter()
    records = load_records(csv_path, dimensions, sample_size)
    load_seconds = time.perf_counter() - start

    start = time.perf_counter()
    buc_cells = buc_cube(records, dimensions, minsup)
    buc_seconds = time.perf_counter() - start

    start = time.perf_counter()
    duckdb_cells = duckdb_cube(csv_path, dimensions, minsup, sample_size)
    duckdb_seconds = time.perf_counter() - start

    comparison = compare_cubes(buc_cells, duckdb_cells)
    return {
        "csv_path": str(csv_path),
        "rows_compared": len(records),
        "dimensions": dimensions,
        "minsup": minsup,
        "buc_seconds": buc_seconds,
        "duckdb_seconds": duckdb_seconds,
        "record_load_seconds": load_seconds,
        **comparison,
    }


def print_report(report: dict[str, Any]) -> None:
    print(f"Rows compared: {report['rows_compared']:,}")
    print(f"Dimensions ({len(report['dimensions'])}): {', '.join(report['dimensions'])}")
    print(f"minsup: {report['minsup']:,}")
    print(f"BUC cells: {report['number_buc_cells']:,}")
    print(f"DuckDB cells: {report['number_duckdb_cells']:,}")
    print(f"Cells only in BUC: {report['cells_only_in_buc']:,}")
    print(f"Cells only in DuckDB: {report['cells_only_in_duckdb']:,}")
    print(f"Support mismatches: {report['support_mismatches']:,}")
    print(
        "Maximum absolute support difference: "
        f"{report['maximum_absolute_support_difference']:,}"
    )
    print(f"BUC runtime: {report['buc_seconds']:.6f} seconds")
    print(f"DuckDB runtime: {report['duckdb_seconds']:.6f} seconds")
    if report["only_in_buc_examples"]:
        print("Example cells only in BUC:", report["only_in_buc_examples"])
    if report["only_in_duckdb_examples"]:
        print("Example cells only in DuckDB:", report["only_in_duckdb_examples"])
    if report["support_mismatch_examples"]:
        print("Example support mismatches:", report["support_mismatch_examples"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, default=Path("M26_DA_A2_Part2.csv"), nargs="?")
    parser.add_argument("--minsup", type=int, default=100)
    parser.add_argument("--sample-size", type=int, default=500)
    parser.add_argument("--full", action="store_true", help="Validate all CSV rows instead of a sample")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    if args.minsup < 1:
        parser.error("--minsup must be positive")
    sample_size = None if args.full else args.sample_size
    if sample_size is not None and sample_size < 1:
        parser.error("--sample-size must be positive")

    report = validate(args.csv_path, SELECTED_DIMENSIONS, args.minsup, sample_size)
    print_report(report)
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"Report written to: {args.output}")


if __name__ == "__main__":
    main()
