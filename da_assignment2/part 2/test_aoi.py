import csv
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from aoi import (
    aggregate_class,
    characteristic_rules,
    discriminant_rules,
    generalized_key,
    load_hierarchies,
)


ROOT = Path(__file__).parent
DATASET = ROOT / "M26_DA_A2_Part2.csv"
HIERARCHIES = ROOT / "aoi_hierarchies.json"


def readable_rule(item: dict) -> str:
    conditions = ", ".join(f"{name}={value}" for name, value in item["rule"].items())
    return (
        f"IF {conditions} THEN income >50K "
        f"[target={item['count_target']}, t={item['t_weight']:.6f}, "
        f"d={item.get('d_weight', 0):.6f}]"
    )


class AoiActualDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hierarchies, cls.conflicts = load_hierarchies(HIERARCHIES, DATASET)
        cls.dimensions = [
            "industry_code_detailed",
            "occupation_code_detailed",
            "household_family_status",
            "state_prev_residence",
            "education",
        ]
        cls.summary_levels = {dimension: 1 for dimension in cls.dimensions}

    def test_all_hierarchies_load_from_external_file(self):
        self.assertEqual(len(self.hierarchies), 5)
        self.assertEqual(
            set(self.hierarchies),
            {
                "industry_code_detailed",
                "occupation_code_detailed",
                "household_family_status",
                "state_prev_residence",
                "education",
            },
        )
        for hierarchy in self.hierarchies.values():
            self.assertEqual(len(hierarchy.levels), 2)
            self.assertTrue(hierarchy.parents[0])

    def test_generalization_of_each_hierarchy(self):
        for hierarchy in self.hierarchies.values():
            detailed_value, summary_value = next(iter(hierarchy.parents[0].items()))
            self.assertEqual(hierarchy.generalize(detailed_value, 0), detailed_value)
            self.assertEqual(hierarchy.generalize(detailed_value, 1), summary_value)
            self.assertEqual(hierarchy.generalize(detailed_value, 2), hierarchy.root)

    def test_attribute_removal_and_unmapped_category(self):
        row = {
            "education": "High school graduate",
            "sex": "Female",
            "unmapped_category": "kept",
        }
        key = generalized_key(
            row,
            ["education", "sex", "unmapped_category"],
            self.hierarchies,
            {"education": 1},
            ["sex"],
        )
        self.assertEqual(dict(key)["education"], "Secondary complete")
        self.assertNotIn("sex", dict(key))
        self.assertEqual(dict(key)["unmapped_category"], "kept")

    def test_missing_unknown_and_zero_support_edges(self):
        education = self.hierarchies["education"]
        self.assertEqual(education.generalize("?", 1), "?")
        self.assertEqual(education.generalize("value absent from JSON", 1), education.root)

        with tempfile.TemporaryDirectory() as directory:
            no_target_dataset = Path(directory) / "no_target.csv"
            with no_target_dataset.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["education", "income"])
                writer.writeheader()
                writer.writerow({"education": "High school graduate", "income": "<=50K"})
            with self.assertRaises(ValueError):
                characteristic_rules(
                    no_target_dataset,
                    ["education"],
                    self.hierarchies,
                    levels={"education": 1},
                )

        rules = characteristic_rules(
            DATASET,
            ["education"],
            self.hierarchies,
            levels={"education": 1},
            minimum_count=10**9,
        )
        self.assertEqual(rules, [])

    def test_aggregated_generalized_tuples_match_direct_csv_count(self):
        dimensions = ["industry_code_detailed"]
        levels = {"industry_code_detailed": 1}
        actual, actual_total = aggregate_class(
            DATASET, dimensions, self.hierarchies, ">50K", levels
        )
        expected = Counter()
        expected_total = 0
        hierarchy = self.hierarchies["industry_code_detailed"]
        with DATASET.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if row["income"] == ">50K":
                    expected_total += 1
                    key = (("industry_code_detailed", hierarchy.generalize(row["industry_code_detailed"], 1)),)
                    expected[key] += 1
        self.assertEqual(actual_total, expected_total)
        self.assertEqual(actual, expected)

    def test_t_weights_are_calculated_from_actual_target_counts(self):
        dimensions = ["education", "sex"]
        levels = {"education": 1}
        counts, total = aggregate_class(DATASET, dimensions, self.hierarchies, ">50K", levels)
        rules = characteristic_rules(DATASET, dimensions, self.hierarchies, levels=levels)
        self.assertTrue(rules)
        for item in rules:
            key = tuple(item["rule"].items())
            self.assertEqual(item["count_target"], counts[key])
            self.assertAlmostEqual(item["t_weight"], counts[key] / total)
        self.assertLessEqual(sum(item["t_weight"] for item in rules), 1.0)

    def test_d_weights_are_calculated_from_both_actual_classes(self):
        dimensions = ["education", "sex"]
        levels = {"education": 1}
        target_counts, target_total = aggregate_class(DATASET, dimensions, self.hierarchies, ">50K", levels)
        contrast_counts, contrast_total = aggregate_class(DATASET, dimensions, self.hierarchies, "<=50K", levels)
        rules = discriminant_rules(DATASET, dimensions, self.hierarchies, levels=levels)
        self.assertTrue(rules)
        for item in rules:
            key = tuple(item["rule"].items())
            expected_target = target_counts[key]
            expected_contrast = contrast_counts[key]
            self.assertEqual(item["count_target"], expected_target)
            self.assertEqual(item["count_contrast"], expected_contrast)
            self.assertAlmostEqual(item["t_weight"], expected_target / target_total)
            self.assertAlmostEqual(item["contrast_weight"], expected_contrast / contrast_total)
            self.assertAlmostEqual(
                item["d_weight"],
                expected_target / target_total - expected_contrast / contrast_total,
            )

    def test_four_existing_pairs_produce_sensible_generalizations(self):
        expected_pairs = {
            "industry_code_detailed": "industry_code_major",
            "occupation_code_detailed": "occupation_code_major",
            "household_family_status": "household_summary",
            "state_prev_residence": "region_prev_residence",
        }
        with DATASET.open(newline="", encoding="utf-8-sig") as handle:
            rows = csv.DictReader(handle)
            observed = {column: defaultdict(Counter) for column in expected_pairs}
            for row in rows:
                for child, parent in expected_pairs.items():
                    if row[child] != "?" and row[parent] != "?":
                        observed[child][row[child]][row[parent]] += 1
        for child, parent in expected_pairs.items():
            hierarchy = self.hierarchies[child]
            self.assertTrue(observed[child])
            self.assertTrue(
                all(
                    hierarchy.generalize(detail, 1) == summaries.most_common(1)[0][0]
                    for detail, summaries in observed[child].items()
                )
            )
            self.assertGreater(
                len({summary for summaries in observed[child].values() for summary in summaries}),
                1,
            )

    def test_very_small_groups_are_retained_when_minimum_count_is_one(self):
        rules = characteristic_rules(
            DATASET,
            ["education", "sex", "industry_code_detailed"],
            self.hierarchies,
            levels={"education": 1, "industry_code_detailed": 1},
            minimum_count=1,
        )
        self.assertTrue(rules)
        self.assertGreaterEqual(min(item["count_target"] for item in rules), 1)
        self.assertTrue(all(item["t_weight"] > 0 for item in rules))

    def test_print_readable_rule_examples(self):
        characteristic = characteristic_rules(
            DATASET,
            self.dimensions,
            self.hierarchies,
            levels=self.summary_levels,
            minimum_count=25,
        )
        discriminant = discriminant_rules(
            DATASET,
            self.dimensions,
            self.hierarchies,
            levels=self.summary_levels,
            minimum_count=25,
        )
        print("\nExample characteristic rules:")
        for item in characteristic[:3]:
            print("  " + readable_rule(item))
        print("Example discriminant rules:")
        for item in discriminant[:3]:
            print("  " + readable_rule(item))
        self.assertGreaterEqual(len(characteristic), 3)
        self.assertGreaterEqual(len(discriminant), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
