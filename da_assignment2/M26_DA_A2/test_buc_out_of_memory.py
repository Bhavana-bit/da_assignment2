import csv
import tempfile
import unittest
from pathlib import Path

from buc import buc
from buc_out_of_memory import buc_out_of_memory, buc_out_of_memory_csv


ROOT = Path(__file__).parent
DATASET = ROOT / "M26_DA_A2_Part2.csv"


class OutOfMemoryBucTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"region": "East", "sex": "F", "tier": "A"},
            {"region": "East", "sex": "M", "tier": "A"},
            {"region": "West", "sex": "M", "tier": "A"},
            {"region": "West", "sex": "M", "tier": "B"},
            {"region": "West", "sex": "F", "tier": "B"},
        ]
        self.dimensions = ["region", "sex", "tier"]

    def test_exact_match_with_in_memory_buc_at_tiny_budget(self):
        expected = buc(self.records, self.dimensions, minsup=2)
        result = buc_out_of_memory(
            (record for record in self.records),
            self.dimensions,
            minsup=2,
            memory_limit_rows=1,
        )
        self.assertEqual(list(result.cells), expected)
        self.assertGreater(result.metrics.partitions_spilled, 0)
        self.assertGreater(result.metrics.bytes_spilled, 0)
        self.assertGreater(result.metrics.pages_processed, 0)
        self.assertGreaterEqual(result.metrics.estimated_peak_buffer_rows, 1)

    def test_budget_changes_spilling_and_preserves_output(self):
        expected = buc(self.records, self.dimensions, minsup=1)
        small = buc_out_of_memory(self.records, self.dimensions, minsup=1, memory_limit_rows=1)
        large = buc_out_of_memory(self.records, self.dimensions, minsup=1, memory_limit_rows=100)
        self.assertEqual(list(small.cells), expected)
        self.assertEqual(list(large.cells), expected)
        self.assertGreater(small.metrics.partitions_spilled, large.metrics.partitions_spilled)
        self.assertGreater(small.metrics.pages_processed, 0)
        self.assertGreater(large.metrics.pages_processed, 0)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            buc_out_of_memory(self.records, self.dimensions, memory_limit_rows=0)
        with self.assertRaises(ValueError):
            buc_out_of_memory(self.records, self.dimensions, measure="sum")
        with self.assertRaises(ValueError):
            buc_out_of_memory([{"region": "East"}], self.dimensions)

    def test_csv_sample_matches_in_memory_buc_without_full_loading(self):
        dimensions = ["sex", "race", "education", "industry_code_major"]
        with DATASET.open(newline="", encoding="utf-8-sig") as handle:
            sample = []
            for row in csv.DictReader(handle):
                sample.append({dimension: row[dimension] for dimension in dimensions})
                if len(sample) == 250:
                    break
        expected = buc(sample, dimensions, minsup=10)
        result_subset = buc_out_of_memory(sample, dimensions, minsup=10, memory_limit_rows=7)
        self.assertEqual(list(result_subset.cells), expected)
        self.assertGreater(result_subset.metrics.input_rows_staged, len(dimensions))
        self.assertGreater(result_subset.metrics.input_bytes_staged, 0)
        self.assertGreaterEqual(result_subset.elapsed_seconds, 0)

        # The CSV adapter is exercised on a bounded temporary CSV, not the full dataset.
        with tempfile.TemporaryDirectory() as directory:
            sample_csv = Path(directory) / "sample.csv"
            with sample_csv.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=dimensions)
                writer.writeheader()
                writer.writerows(sample)
            csv_result = buc_out_of_memory_csv(
                sample_csv, dimensions, minsup=10, memory_limit_rows=7
            )
        self.assertEqual(list(csv_result.cells), expected)

    def test_temporary_spill_directory_is_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            result = buc_out_of_memory(self.records, self.dimensions, minsup=1, memory_limit_rows=1)
            self.assertTrue(result.cells)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
