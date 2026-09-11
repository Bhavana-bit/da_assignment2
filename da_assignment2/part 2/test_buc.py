import unittest

from buc import ALL, buc, timed_buc


class BucTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"region": "East", "sex": "F"},
            {"region": "East", "sex": "M"},
            {"region": "West", "sex": "M"},
            {"region": "West", "sex": "M"},
        ]

    def test_recursive_buc_emits_all_qualifying_cells_and_prunes(self):
        cells = buc(self.records, ["region", "sex"], minsup=2)
        actual = {(tuple(cell["dimensions"].items()), cell["measure"]) for cell in cells}
        expected = {
            ((("region", ALL), ("sex", ALL)), 4),
            ((("region", "East"), ("sex", ALL)), 2),
            ((("region", "West"), ("sex", ALL)), 2),
            ((("region", ALL), ("sex", "M")), 3),
            ((("region", "West"), ("sex", "M")), 2),
        }
        self.assertEqual(actual, expected)
        self.assertNotIn(
            (("region", "East"), ("sex", "F")),
            {tuple(cell["dimensions"].items()) for cell in cells},
        )

    def test_dimension_order_and_determinism(self):
        first = buc(self.records, ["sex", "region"], minsup=1)
        second = buc(self.records, ["sex", "region"], minsup=1)
        self.assertEqual(first, second)
        self.assertTrue(all(list(cell["dimensions"]) == ["sex", "region"] for cell in first))

    def test_count_measure_and_generator_input(self):
        cells = buc((record for record in self.records), ["region"], measure="COUNT(*)", minsup=1)
        self.assertEqual(
            [cell["measure"] for cell in cells if cell["dimensions"]["region"] != ALL],
            [2, 2],
        )

    def test_timing_wrapper(self):
        result = timed_buc(self.records, ["region"], minsup=2)
        self.assertTrue(result.cells)
        self.assertGreaterEqual(result.elapsed_seconds, 0)

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            buc(self.records, ["region", "region"])
        with self.assertRaises(ValueError):
            buc(self.records, ["region"], measure="sum")
        with self.assertRaises(ValueError):
            buc(self.records, ["region"], minsup=0)
        with self.assertRaises(ValueError):
            buc([{"sex": "F"}], ["region"])
        with self.assertRaises(TypeError):
            buc([("East",)], ["region"])

    def test_empty_and_zero_support_outputs(self):
        self.assertEqual(buc([], ["region"], minsup=1), [])
        self.assertEqual(buc(self.records, ["region"], minsup=10), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)