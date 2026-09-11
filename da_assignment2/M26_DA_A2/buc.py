#!/usr/bin/env python3
"""A deterministic, from-scratch Bottom-Up Cube implementation.

The primary supported measure is COUNT(*).  The public ``buc`` function
returns one dictionary per qualifying cube cell.  Each dictionary contains a
``dimensions`` mapping in the requested order and a ``measure`` count.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence


ALL = "ALL"
COUNT_MEASURES = {"count", "count(*)", "COUNT(*)"}


@dataclass(frozen=True)
class CubeCell:
    """One iceberg cube cell, with dimensions retained in requested order."""

    dimensions: tuple[tuple[str, Any], ...]
    measure: int

    def as_dict(self) -> dict[str, Any]:
        return {"dimensions": dict(self.dimensions), "measure": self.measure}


@dataclass(frozen=True)
class TimedCube:
    """Cube output together with wall-clock runtime."""

    cells: tuple[dict[str, Any], ...]
    elapsed_seconds: float


def _validate_inputs(
    records: Sequence[Mapping[str, Any]], dimensions: Sequence[str], measure: str, minsup: int
) -> None:
    if not isinstance(dimensions, Sequence) or isinstance(dimensions, (str, bytes)):
        raise TypeError("dimensions must be a sequence of column names")
    if not dimensions or any(not isinstance(dimension, str) or not dimension for dimension in dimensions):
        raise ValueError("dimensions must contain at least one non-empty string")
    if len(set(dimensions)) != len(dimensions):
        raise ValueError("dimensions must not contain duplicates")
    if measure not in COUNT_MEASURES:
        raise ValueError("Only COUNT(*) is supported; use measure='count'")
    if isinstance(minsup, bool) or not isinstance(minsup, int) or minsup < 1:
        raise ValueError("minsup must be a positive integer")
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise TypeError(f"record {index} is not a mapping")
        missing = [dimension for dimension in dimensions if dimension not in record]
        if missing:
            raise ValueError(f"record {index} is missing dimensions: {missing}")


def _value_sort_key(value: Any) -> tuple[str, str]:
    """Sort heterogeneous category values without relying on cross-type ordering."""
    return type(value).__name__, repr(value)


def buc(
    records: Iterable[Mapping[str, Any]],
    dimensions: Sequence[str],
    measure: str = "count",
    minsup: int = 1,
) -> list[dict[str, Any]]:
    """Compute an iceberg cube using recursive Bottom-Up Cube partitioning.

    At each recursion level, each remaining dimension is considered as the
    next partition choice. Partitions below ``minsup`` are discarded before
    recursion. The current prefix with ``ALL`` for every unselected dimension
    is emitted before descending. This enumerates subsets of dimensions, not
    the Cartesian product of category values, and therefore includes cells
    such as ``(ALL, value)`` as well as ``(value, ALL)``.

    Args:
        records: Iterable of mappings containing the requested dimensions.
        dimensions: Dimension names. Their order is preserved in every cell.
        measure: ``"count"`` or an equivalent COUNT(*) spelling.
        minsup: Minimum COUNT(*) support for an emitted cell and partition.

    Returns:
        Deterministically ordered list of ``{"dimensions": ..., "measure": ...}``
        dictionaries. ``ALL`` represents an aggregated dimension.
    """
    materialized = list(records)
    _validate_inputs(materialized, dimensions, measure, minsup)
    ordered_dimensions = tuple(dimensions)
    cells: list[dict[str, Any]] = []

    def recurse(
        current_records: list[Mapping[str, Any]],
        first_dimension: int,
        selected: dict[str, Any],
    ) -> None:
        support = len(current_records)
        if support < minsup:
            return
        all_cell = tuple(
            (dimension, selected.get(dimension, ALL)) for dimension in ordered_dimensions
        )
        cells.append(CubeCell(all_cell, support).as_dict())
        for dimension_index in range(first_dimension, len(ordered_dimensions)):
            dimension = ordered_dimensions[dimension_index]
            partitions: defaultdict[Any, list[Mapping[str, Any]]] = defaultdict(list)
            for record in current_records:
                partitions[record[dimension]].append(record)
            for value in sorted(partitions, key=_value_sort_key):
                partition = partitions[value]
                if len(partition) >= minsup:
                    next_selected = dict(selected)
                    next_selected[dimension] = value
                    recurse(partition, dimension_index + 1, next_selected)

    recurse(materialized, 0, {})
    return cells


def timed_buc(
    records: Iterable[Mapping[str, Any]],
    dimensions: Sequence[str],
    measure: str = "count",
    minsup: int = 1,
) -> TimedCube:
    """Run :func:`buc` and return its deterministic output with elapsed time."""
    start = perf_counter()
    cells = buc(records, dimensions, measure, minsup)
    return TimedCube(tuple(cells), perf_counter() - start)
