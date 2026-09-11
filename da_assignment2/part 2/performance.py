"""Benchmark the disk-backed and in-memory BUC implementations.

The script samples a bounded number of CSV rows, runs three timing experiments,
and saves the resulting runtime charts under ``plots/``.
"""

from __future__ import annotations

import csv
import argparse
from pathlib import Path
from time import perf_counter
from typing import Any

from buc import timed_buc
from buc_out_of_memory import buc_out_of_memory


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
REPEATS = 2


def load_sample(csv_path: Path, dimensions: list[str], limit: int = SAMPLE_SIZE) -> list[dict[str, Any]]:
    """Read only the requested columns from the first ``limit`` CSV rows."""
    sample: list[dict[str, Any]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            sample.append({dimension: row[dimension] for dimension in dimensions})
            if len(sample) >= limit:
                break
    return sample


def average_disk_runtime(
    records: list[dict[str, Any]], minsup: int, memory_limit_rows: int
) -> float:
    """Run disk-backed BUC repeatedly and return average wall-clock time."""
    times = []
    for repeat in range(1, REPEATS + 1):
        start = perf_counter()
        buc_out_of_memory(
            records,
            DIMENSIONS,
            minsup=minsup,
            memory_limit_rows=memory_limit_rows,
        )
        elapsed = perf_counter() - start
        times.append(elapsed)
        print(
            f"  run {repeat}/{REPEATS}: minsup={minsup}, "
            f"memory_limit_rows={memory_limit_rows}, {elapsed:.4f}s"
        )
    return sum(times) / len(times)


def average_in_memory_runtime(records: list[dict[str, Any]], dimensions: list[str], minsup: int) -> float:
    """Run in-memory BUC repeatedly and return average wall-clock time."""
    times = []
    for repeat in range(1, REPEATS + 1):
        start = perf_counter()
        timed_buc(records, dimensions, minsup=minsup)
        elapsed = perf_counter() - start
        times.append(elapsed)
        print(f"  run {repeat}/{REPEATS}: dimensions={len(dimensions)}, {elapsed:.4f}s")
    return sum(times) / len(times)


def plot_line(x_values: list[int], y_values: list[float], xlabel: str, title: str, path: Path) -> None:
    """Save one consistently formatted runtime plot."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots()
    axis.plot(x_values, y_values, marker="o")
    axis.set_xscale("log") if xlabel != "Number of dimensions" else None
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel("Average runtime (seconds)")
    axis.grid(True)
    figure.tight_layout()
    figure.savefig(path)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=Path(__file__).with_name("M26_DA_A2_Part2.csv"),
    )
    args = parser.parse_args()
    csv_path = args.csv_path
    plots_dir = Path(__file__).with_name("plots")
    plots_dir.mkdir(exist_ok=True)
    records = load_sample(csv_path, DIMENSIONS)
    print(f"Loaded {len(records):,} sampled rows from {csv_path.name}")

    print("\nExperiment 1: minsup vs runtime")
    minsup_values = [10, 25, 50, 100, 250]
    minsup_times = []
    for minsup in minsup_values:
        minsup_times.append(average_disk_runtime(records, minsup, memory_limit_rows=2000))
    plot_line(
        minsup_values,
        minsup_times,
        "Minimum support (log scale)",
        "BUC runtime vs minimum support",
        plots_dir / "minsup_vs_runtime.png",
    )

    print("\nExperiment 2: memory limit vs runtime")
    memory_values = [20, 50, 200, 500, 2000]
    memory_times = []
    for memory_limit_rows in memory_values:
        memory_times.append(average_disk_runtime(records, minsup=50, memory_limit_rows=memory_limit_rows))
    plot_line(
        memory_values,
        memory_times,
        "Memory limit (rows, log scale)",
        "BUC runtime vs memory limit",
        plots_dir / "memory_vs_runtime.png",
    )

    print("\nExperiment 3: number of dimensions vs runtime")
    dimension_counts = [3, 5, 7, 9, 12]
    dimension_times = []
    for count in dimension_counts:
        dimensions = DIMENSIONS[:count]
        dimension_times.append(average_in_memory_runtime(records, dimensions, minsup=10))
    plot_line(
        dimension_counts,
        dimension_times,
        "Number of dimensions",
        "BUC runtime vs number of dimensions",
        plots_dir / "dims_vs_runtime.png",
    )

    print("\nSummary")
    print("minsup experiment:", dict(zip(minsup_values, minsup_times)))
    print("memory experiment:", dict(zip(memory_values, memory_times)))
    print("dimension experiment:", dict(zip(dimension_counts, dimension_times)))


if __name__ == "__main__":
    main()
