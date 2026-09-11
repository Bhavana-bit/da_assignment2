#!/usr/bin/env python3
"""Streaming Attribute-Oriented Induction for the Part II census data.

The implementation uses these definitions:

    t_weight(X) = count_target(X) / total_target
    c_weight(X) = count_contrast(X) / total_contrast
    d_weight(X) = t_weight(X) - c_weight(X)

The d-weight is a class-relative support difference. Positive values indicate
that a generalized pattern is more prevalent in the target class; negative
values indicate the contrasting class. All hierarchy definitions are loaded
from a JSON file at runtime.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Hierarchy:
    name: str
    levels: tuple[str, ...]
    parents: dict[str, dict[str, str]]
    root: str
    missing_value: str

    def generalize(self, value: str, level: int) -> str:
        """Traverse from the detailed level to the requested hierarchy level."""
        if level < 0 or level > len(self.levels):
            raise ValueError(f"Invalid level {level} for hierarchy {self.name}")
        if value == self.missing_value:
            return value
        if level == len(self.levels):
            return self.root
        generalized = value
        for current_level in range(level):
            generalized = self.parents[current_level].get(generalized, self.root)
        return generalized if level < len(self.levels) else self.root


def load_hierarchies(config_path: Path, dataset_path: Path) -> tuple[dict[str, Hierarchy], list[str]]:
    """Load JSON hierarchy definitions and resolve dataset-backed mappings."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    missing = config.get("missing_value", "?")
    root = config.get("root_value", "ANY")
    definitions = config["hierarchies"]
    source_definitions = [item for item in definitions if "mapping_source" in item]
    source_counts: dict[tuple[str, str], dict[str, Counter[str]]] = {
        (item["mapping_source"]["child_column"], item["mapping_source"]["parent_column"]): defaultdict(Counter)
        for item in source_definitions
    }
    if source_counts:
        with dataset_path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                for child_column, parent_column in source_counts:
                    child = row[child_column]
                    parent = row[parent_column]
                    if child != missing and parent != missing:
                        source_counts[(child_column, parent_column)][child][parent] += 1

    hierarchies: dict[str, Hierarchy] = {}
    conflict_notes: list[str] = []
    for definition in definitions:
        levels = tuple(definition["levels"])
        if len(levels) != 2:
            raise ValueError("Each AOI hierarchy must currently contain detailed and summary levels.")
        if "mapping" in definition:
            mapping = dict(definition["mapping"])
        else:
            source = definition["mapping_source"]
            observed = source_counts[(source["child_column"], source["parent_column"])]
            mapping = {}
            for child, parent_counts in observed.items():
                chosen_parent, chosen_count = parent_counts.most_common(1)[0]
                mapping[child] = chosen_parent
                if len(parent_counts) > 1:
                    conflict_notes.append(
                        f"{definition['name']}:{child!r} resolved to {chosen_parent!r} "
                        f"using the most frequent parent ({chosen_count} observations)."
                    )
        hierarchies[levels[0]] = Hierarchy(
            name=definition["name"],
            levels=levels,
            parents={0: mapping},
            root=root,
            missing_value=missing,
        )
    return hierarchies, conflict_notes


def generalized_key(
    row: dict[str, str],
    dimensions: Iterable[str],
    hierarchies: dict[str, Hierarchy],
    levels: dict[str, int] | None = None,
    removed_attributes: Iterable[str] = (),
) -> tuple[tuple[str, str], ...]:
    """Apply attribute removal and hierarchy traversal to one input tuple."""
    level_by_dimension = levels or {}
    removed = set(removed_attributes)
    result = []
    for dimension in dimensions:
        if dimension in removed:
            continue
        value = row[dimension]
        hierarchy = hierarchies.get(dimension)
        if hierarchy is not None:
            value = hierarchy.generalize(value, level_by_dimension.get(dimension, 0))
        result.append((dimension, value))
    return tuple(result)


def aggregate_class(
    dataset_path: Path,
    dimensions: list[str],
    hierarchies: dict[str, Hierarchy],
    class_value: str,
    levels: dict[str, int] | None = None,
    removed_attributes: Iterable[str] = (),
) -> tuple[Counter[tuple[tuple[str, str], ...]], int]:
    """Stream one class and count generalized tuples without dataframe grouping."""
    counts: Counter[tuple[tuple[str, str], ...]] = Counter()
    total = 0
    with dataset_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["income"] != class_value:
                continue
            total += 1
            counts[generalized_key(row, dimensions, hierarchies, levels, removed_attributes)] += 1
    return counts, total


def characteristic_rules(
    dataset_path: Path,
    dimensions: list[str],
    hierarchies: dict[str, Hierarchy],
    target_class: str = ">50K",
    levels: dict[str, int] | None = None,
    removed_attributes: Iterable[str] = (),
    minimum_count: int = 1,
) -> list[dict[str, Any]]:
    """Generate target-class characteristic rules with t-weights."""
    counts, total = aggregate_class(
        dataset_path, dimensions, hierarchies, target_class, levels, removed_attributes
    )
    if total == 0:
        raise ValueError(f"No rows found for target class {target_class!r}.")
    rules = []
    for key, count in counts.items():
        if count < minimum_count:
            continue
        rules.append({
            "rule": dict(key),
            "count_target": count,
            "t_weight": count / total,
            "target_class": target_class,
        })
    return sorted(rules, key=lambda item: (-item["t_weight"], str(item["rule"])))


def discriminant_rules(
    dataset_path: Path,
    dimensions: list[str],
    hierarchies: dict[str, Hierarchy],
    target_class: str = ">50K",
    contrast_class: str = "<=50K",
    levels: dict[str, int] | None = None,
    removed_attributes: Iterable[str] = (),
    minimum_count: int = 1,
) -> list[dict[str, Any]]:
    """Compare target and contrast class supports and calculate d-weights."""
    target_counts, target_total = aggregate_class(
        dataset_path, dimensions, hierarchies, target_class, levels, removed_attributes
    )
    contrast_counts, contrast_total = aggregate_class(
        dataset_path, dimensions, hierarchies, contrast_class, levels, removed_attributes
    )
    if target_total == 0 or contrast_total == 0:
        raise ValueError("Both target and contrast classes must contain rows.")
    rules = []
    for key in set(target_counts) | set(contrast_counts):
        target_count = target_counts[key]
        contrast_count = contrast_counts[key]
        if target_count < minimum_count:
            continue
        target_weight = target_count / target_total
        contrast_weight = contrast_count / contrast_total
        rules.append({
            "rule": dict(key),
            "count_target": target_count,
            "count_contrast": contrast_count,
            "t_weight": target_weight,
            "contrast_weight": contrast_weight,
            "d_weight": target_weight - contrast_weight,
            "target_class": target_class,
            "contrast_class": contrast_class,
        })
    return sorted(rules, key=lambda item: (-item["d_weight"], str(item["rule"])))


def write_rules(path: Path, rules: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(rules, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, default=Path("M26_DA_A2_Part2.csv"), nargs="?")
    parser.add_argument("--hierarchies", type=Path, default=Path("aoi_hierarchies.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("aoi_results"))
    parser.add_argument("--minimum-count", type=int, default=25)
    args = parser.parse_args()

    hierarchies, conflicts = load_hierarchies(args.hierarchies, args.csv_path)
    dimensions = [
        "industry_code_detailed", "occupation_code_detailed", "household_family_status",
        "state_prev_residence", "education",
    ]
    levels = {dimension: 1 for dimension in dimensions}
    characteristic = characteristic_rules(
        args.csv_path, dimensions, hierarchies, levels=levels, minimum_count=args.minimum_count
    )
    discriminant = discriminant_rules(
        args.csv_path, dimensions, hierarchies, levels=levels, minimum_count=args.minimum_count
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_rules(args.output_dir / "characteristic_rules.json", characteristic)
    write_rules(args.output_dir / "discriminant_rules.json", discriminant)
    (args.output_dir / "run_metadata.json").write_text(json.dumps({
        "dimensions": dimensions,
        "levels": levels,
        "removed_attributes": [],
        "minimum_count": args.minimum_count,
        "hierarchy_conflicts_resolved": conflicts,
        "formulas": {
            "t_weight": "count_target / total_target",
            "contrast_weight": "count_contrast / total_contrast",
            "d_weight": "t_weight - contrast_weight",
        },
    }, indent=2), encoding="utf-8")
    print(f"Characteristic rules: {len(characteristic)}")
    print(f"Discriminant rules: {len(discriminant)}")
    print(f"Hierarchy conflicts resolved by mode: {len(conflicts)}")
    print(f"Results written to: {args.output_dir}")


if __name__ == "__main__":
    main()