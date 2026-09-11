"""Benchmark an indexed-partition optimization for Bottom-Up Cube.

The optimized implementation stores requested dimension values in tuples and
partitions by integer column position, avoiding repeated dictionary lookups in
the recursive hot path while preserving BUC's output order exactly.
"""

from __future__ import annotations

import csv
import argparse
from pathlib import Path
from time import perf_counter
from collections import defaultdict
from typing import Any, Mapping, Sequence

from buc import ALL, buc


DIMENSIONS = [
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
SAMPLE_SIZE = 300
REPEATS = 3


def optimized_buc(
    records: Sequence[Mapping[str, Any]],
    dimensions: Sequence[str],
    measure: str = "count",
    minsup: int = 1,
) -> list[dict[str, Any]]:
    """Run BUC with tuple rows and integer dimension positions.

    The tuple conversion is intentionally part of this function's runtime so
    the benchmark measures the complete end-to-end cost of the optimization.
    """
    if isinstance(dimensions, (str, bytes)) or not dimensions:
        raise ValueError("dimensions must contain at least one dimension")
    if len(set(dimensions)) != len(dimensions):
        raise ValueError("dimensions must not contain duplicates")
    if measure not in {"count", "count(*)", "COUNT(*)"}:
        raise ValueError("Only COUNT(*) is supported; use measure='count'")
    if isinstance(minsup, bool) or not isinstance(minsup, int) or minsup < 1:
        raise ValueError("minsup must be a positive integer")

    ordered_dimensions = tuple(dimensions)
    rows = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise TypeError(f"record {index} is not a mapping")
        try:
            rows.append(tuple(record[dimension] for dimension in ordered_dimensions))
        except KeyError as error:
            raise ValueError(f"record {index} is missing dimension: {error.args[0]}") from error

    selected = [ALL] * len(ordered_dimensions)
    cells: list[dict[str, Any]] = []

    def recurse(current_rows: list[tuple[Any, ...]], first_dimension: int) -> None:
        support = len(current_rows)
        if support < minsup:
            return
        cells.append({
            "dimensions": dict(zip(ordered_dimensions, selected)),
            "measure": support,
        })
        for dimension_index in range(first_dimension, len(ordered_dimensions)):
            partitions: defaultdict[Any, list[tuple[Any, ...]]] = defaultdict(list)
            for row in current_rows:
                partitions[row[dimension_index]].append(row)
            for value in sorted(partitions, key=lambda item: (type(item).__name__, repr(item))):
                partition = partitions[value]
                if len(partition) >= minsup:
                    selected[dimension_index] = value
                    recurse(partition, dimension_index + 1)
                    selected[dimension_index] = ALL

    recurse(rows, 0)
    return cells


def load_sample(csv_path: Path, dimensions: Sequence[str], limit: int = SAMPLE_SIZE) -> list[dict[str, str]]:
    """Read a bounded sample through DictReader instead of loading the CSV."""
    sample: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            sample.append({dimension: row[dimension] for dimension in dimensions})
            if len(sample) >= limit:
                break
    return sample


def benchmark(csv_path: Path | None = None) -> None:
    """Compare ordinary BUC with the indexed-partition implementation."""
    import matplotlib.pyplot as plt

    if csv_path is None:
        csv_path = Path(__file__).with_name("M26_DA_A2_Part2.csv")
    records = load_sample(csv_path, DIMENSIONS)
    minsup_values = [10, 25, 50, 100]
    results = []
    correctness_passed = True

    for minsup in minsup_values:
        unoptimized_times = []
        optimized_times = []
        expected = buc(records, DIMENSIONS, minsup=minsup)
        for repeat in range(1, REPEATS + 1):
            start = perf_counter()
            unoptimized = buc(records, DIMENSIONS, minsup=minsup)
            unoptimized_times.append(perf_counter() - start)
            if unoptimized != expected:
                raise AssertionError(f"Unoptimized BUC changed at minsup={minsup}")

            start = perf_counter()
            optimized = optimized_buc(records, DIMENSIONS, minsup=minsup)
            optimized_times.append(perf_counter() - start)
            if optimized != expected:
                correctness_passed = False
                raise AssertionError(f"Optimized BUC differs at minsup={minsup}")
            print(f"minsup={minsup}, run {repeat}/{REPEATS} complete")

        unoptimized_average = sum(unoptimized_times) / len(unoptimized_times)
        optimized_average = sum(optimized_times) / len(optimized_times)
        results.append((minsup, unoptimized_average, optimized_average))

    print("\nminsup | unoptimized (s) | optimized (s) | speedup | result")
    print("-------|------------------|---------------|---------|----------")
    for minsup, unoptimized, optimized in results:
        speedup = unoptimized / optimized if optimized else float("inf")
        result = "improved" if speedup > 1 else "slower" if speedup < 1 else "equal"
        print(
            f"{minsup:6} | {unoptimized:16.6f} | {optimized:13.6f} | "
            f"{speedup:7.2f}x | {result}"
        )
    baseline_average = sum(item[1] for item in results) / len(results)
    optimized_average = sum(item[2] for item in results) / len(results)
    print(f"\nBaseline BUC runtime: {baseline_average:.6f} seconds")
    print(f"Optimized BUC runtime: {optimized_average:.6f} seconds")
    print(f"Speedup: {baseline_average / optimized_average:.2f}x")
    print(f"Correctness: {'PASS' if correctness_passed else 'FAIL'}")

    plots_dir = Path(__file__).with_name("plots")
    plots_dir.mkdir(exist_ok=True)
    labels = [str(minsup) for minsup, _, _ in results]
    unoptimized_values = [unoptimized for _, unoptimized, _ in results]
    optimized_values = [optimized for _, _, optimized in results]
    positions = list(range(len(results)))
    width = 0.35
    figure, axis = plt.subplots()
    axis.bar([position - width / 2 for position in positions], unoptimized_values, width, label="BUC")
    axis.bar([position + width / 2 for position in positions], optimized_values, width, label="Optimized BUC")
    axis.set_title("BUC optimization benchmark")
    axis.set_xlabel("Minimum support")
    axis.set_ylabel("Average runtime (seconds)")
    axis.set_xticks(positions, labels)
    axis.grid(True, axis="y")
    axis.legend()
    figure.tight_layout()
    figure.savefig(plots_dir / "optimization_benchmark.png")
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=Path(__file__).with_name("M26_DA_A2_Part2.csv"),
    )
    benchmark(parser.parse_args().csv_path)
