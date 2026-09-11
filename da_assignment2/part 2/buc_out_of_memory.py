#!/usr/bin/env python3
"""Disk-backed, out-of-memory Bottom-Up Cube for COUNT(*).

This module intentionally does not call the in-memory BUC implementation.
"""

from __future__ import annotations

import argparse
import csv
import pickle
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

from buc import ALL


COUNT_MEASURES = {"count", "count(*)", "COUNT(*)"}


@dataclass
class OutOfMemoryMetrics:
    """Instrumentation collected during one disk-backed BUC run.

    ``estimated_peak_buffer_rows`` counts rows in active partition buffers plus
    the current read page. It is an estimate of algorithm-managed row storage,
    not process RSS and not a byte-precise measurement.
    """

    estimated_peak_buffer_rows: int = 0
    partitions_spilled: int = 0
    bytes_spilled: int = 0
    pages_processed: int = 0
    input_rows_staged: int = 0
    input_bytes_staged: int = 0


@dataclass(frozen=True)
class OutOfMemoryResult:
    cells: tuple[dict[str, Any], ...]
    metrics: OutOfMemoryMetrics
    elapsed_seconds: float
    memory_limit_rows: int


@dataclass
class _Partition:
    count: int
    records: list[Mapping[str, Any]] | None = None
    path: Path | None = None


@dataclass
class _RunState:
    dimensions: tuple[str, ...]
    minsup: int
    memory_limit_rows: int
    temp_dir: Path
    metrics: OutOfMemoryMetrics = field(default_factory=OutOfMemoryMetrics)
    next_file_id: int = 0

    def new_partition_path(self) -> Path:
        path = self.temp_dir / f"partition_{self.next_file_id:08d}.pkl"
        self.next_file_id += 1
        return path


def _validate_inputs(
    dimensions: Sequence[str], measure: str, minsup: int, memory_limit_rows: int
) -> None:
    if not dimensions or any(not isinstance(dimension, str) or not dimension for dimension in dimensions):
        raise ValueError("dimensions must contain at least one non-empty string")
    if len(set(dimensions)) != len(dimensions):
        raise ValueError("dimensions must not contain duplicates")
    if measure not in COUNT_MEASURES:
        raise ValueError("Only COUNT(*) is supported; use measure='count'")
    if isinstance(minsup, bool) or not isinstance(minsup, int) or minsup < 1:
        raise ValueError("minsup must be a positive integer")
    if isinstance(memory_limit_rows, bool) or not isinstance(memory_limit_rows, int) or memory_limit_rows < 1:
        raise ValueError("memory_limit_rows must be a positive integer")


def _read_pages(source: _Partition, page_size: int, state: _RunState):
    if source.records is not None:
        for start in range(0, len(source.records), page_size):
            page = source.records[start : start + page_size]
            state.metrics.pages_processed += 1
            yield page
        return
    if source.path is None:
        return
    with source.path.open("rb") as handle:
        while True:
            page = []
            try:
                for _ in range(page_size):
                    page.append(pickle.load(handle))
            except EOFError:
                pass
            if not page:
                break
            state.metrics.pages_processed += 1
            yield page


def _update_peak(state: _RunState, source: _Partition, page_rows: int, buffered_rows: int) -> None:
    resident_source_rows = len(source.records) if source.records is not None else 0
    estimated_rows = resident_source_rows + page_rows + buffered_rows
    state.metrics.estimated_peak_buffer_rows = max(
        state.metrics.estimated_peak_buffer_rows, estimated_rows
    )


def _append_records(path: Path, records: list[Mapping[str, Any]], state: _RunState) -> None:
    if not records:
        return
    before = path.stat().st_size if path.exists() else 0
    with path.open("ab") as handle:
        for record in records:
            pickle.dump(dict(record), handle, protocol=pickle.HIGHEST_PROTOCOL)
    state.metrics.bytes_spilled += path.stat().st_size - before


def _partition_source(
    source: _Partition, dimension: str, state: _RunState
) -> dict[Any, _Partition]:
    """Partition a source, flushing buffered groups when the row budget is reached."""
    buffers: dict[Any, list[Mapping[str, Any]]] = defaultdict(list)
    paths: dict[Any, Path] = {}
    counts: dict[Any, int] = defaultdict(int)
    buffered_rows = 0

    def flush_buffers() -> None:
        nonlocal buffered_rows
        for value, records in buffers.items():
            if not records:
                continue
            if value not in paths:
                paths[value] = state.new_partition_path()
                state.metrics.partitions_spilled += 1
            _append_records(paths[value], records, state)
            buffers[value] = []
        buffered_rows = 0

    for page in _read_pages(source, state.memory_limit_rows, state):
        _update_peak(state, source, len(page), buffered_rows)
        for record in page:
            value = record[dimension]
            buffers[value].append(record)
            counts[value] += 1
            buffered_rows += 1
            if buffered_rows >= state.memory_limit_rows:
                flush_buffers()
        _update_peak(state, source, len(page), buffered_rows)

    result: dict[Any, _Partition] = {}
    for value in sorted(counts, key=lambda item: (type(item).__name__, repr(item))):
        if value in paths:
            _append_records(paths[value], buffers[value], state)
            result[value] = _Partition(count=counts[value], path=paths[value])
        else:
            result[value] = _Partition(count=counts[value], records=buffers[value])
    return result


def _stage_records(
    records: Iterable[Mapping[str, Any]], dimensions: tuple[str, ...], state: _RunState
) -> _Partition:
    """Stage the input iterable incrementally, never retaining the full input."""
    path = state.new_partition_path()
    count = 0
    with path.open("wb") as handle:
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise TypeError(f"record {index} is not a mapping")
            missing = [dimension for dimension in dimensions if dimension not in record]
            if missing:
                raise ValueError(f"record {index} is missing dimensions: {missing}")
            pickle.dump(dict(record), handle, protocol=pickle.HIGHEST_PROTOCOL)
            count += 1
    state.metrics.input_rows_staged = count
    state.metrics.input_bytes_staged = path.stat().st_size
    return _Partition(count=count, path=path)


def buc_out_of_memory(
    records: Iterable[Mapping[str, Any]],
    dimensions: Sequence[str],
    measure: str = "count",
    minsup: int = 1,
    memory_limit_rows: int = 1000,
) -> OutOfMemoryResult:
    """Compute an iceberg cube using disk-backed recursive BUC.

    ``memory_limit_rows`` is the maximum number of rows held in all active
    partition buffers before those buffers are appended to temporary pickle
    files. Read pages are also capped at this size. It is a row-count budget,
    not a byte budget and not a process-RSS measurement. Smaller values cause
    more frequent disk flushing and more pages; larger values retain more
    partition rows in memory. Temporary files are removed when this function
    exits, including on exceptions.
    """
    ordered_dimensions = tuple(dimensions)
    _validate_inputs(ordered_dimensions, measure, minsup, memory_limit_rows)
    start = perf_counter()
    cells: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="buc_oos_") as directory:
        state = _RunState(
            dimensions=ordered_dimensions,
            minsup=minsup,
            memory_limit_rows=memory_limit_rows,
            temp_dir=Path(directory),
        )
        root = _stage_records(records, ordered_dimensions, state)

        def recurse(source: _Partition, first_dimension: int, selected: dict[str, Any]) -> None:
            if source.count < minsup:
                return
            cells.append({
                "dimensions": {
                    dimension: selected.get(dimension, ALL)
                    for dimension in ordered_dimensions
                },
                "measure": source.count,
            })
            for dimension_index in range(first_dimension, len(ordered_dimensions)):
                dimension = ordered_dimensions[dimension_index]
                partitions = _partition_source(source, dimension, state)
                for value, partition in partitions.items():
                    if partition.count >= minsup:
                        next_selected = dict(selected)
                        next_selected[dimension] = value
                        recurse(partition, dimension_index + 1, next_selected)

        recurse(root, 0, {})
        result = OutOfMemoryResult(
            cells=tuple(cells),
            metrics=state.metrics,
            elapsed_seconds=perf_counter() - start,
            memory_limit_rows=memory_limit_rows,
        )
    return result


def buc_out_of_memory_csv(
    csv_path: Path,
    dimensions: Sequence[str],
    measure: str = "count",
    minsup: int = 1,
    memory_limit_rows: int = 1000,
) -> OutOfMemoryResult:
    """Stream a CSV into disk-backed BUC without loading it into RAM."""
    def records() -> Iterable[Mapping[str, str]]:
        with csv_path.open(newline="", encoding="utf-8-sig") as handle:
            yield from csv.DictReader(handle)

    return buc_out_of_memory(records(), dimensions, measure, minsup, memory_limit_rows)


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--minsup", type=int, default=100)
    parser.add_argument("--memory-limit-rows", type=int, default=1000)
    parser.add_argument("--dimensions", nargs="+", required=True)
    args = parser.parse_args()
    result = buc_out_of_memory_csv(
        args.csv_path,
        args.dimensions,
        minsup=args.minsup,
        memory_limit_rows=args.memory_limit_rows,
    )
    print(f"Cells: {len(result.cells):,}")
    print(f"Runtime: {result.elapsed_seconds:.6f} seconds")
    print(f"Memory limit (rows): {result.memory_limit_rows:,}")
    print(f"Estimated peak buffered rows: {result.metrics.estimated_peak_buffer_rows:,}")
    print(f"Partitions spilled: {result.metrics.partitions_spilled:,}")
    print(f"Bytes spilled: {result.metrics.bytes_spilled:,}")
    print(f"Pages processed: {result.metrics.pages_processed:,}")
    print(f"Input rows staged: {result.metrics.input_rows_staged:,}")
    print(f"Input bytes staged: {result.metrics.input_bytes_staged:,}")


if __name__ == "__main__":
    _main()
