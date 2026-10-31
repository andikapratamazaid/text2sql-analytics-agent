import unittest

from evaluation.compare import results_match


class TestCompare(unittest.TestCase):
    def ok(self, *a, **k):
        return results_match(*a, **k)[0]

    def test_scalar_match_and_rounding(self):
        self.assertTrue(self.ok(["x"], [(1.23,)], ["total"], [(1.234,)]))
        self.assertTrue(self.ok(["x"], [(5,)], ["n"], [(5.0,)]))
        self.assertFalse(self.ok(["x"], [(5,)], ["n"], [(6,)]))

    def test_extra_columns_and_reordering_are_allowed(self):
        gold = (["state", "n"], [("SP", 10), ("RJ", 5)])
        self.assertTrue(self.ok(*gold, ["n", "state", "pct"], [(5, "RJ", 33.3), (10, "SP", 66.7)]))

    def test_values_must_line_up_row_by_row(self):
        gold = (["state", "n"], [("SP", 10), ("RJ", 5)])
        self.assertFalse(self.ok(*gold, ["state", "n"], [("SP", 5), ("RJ", 10)]))

    def test_missing_column_fails(self):
        self.assertFalse(self.ok(["a", "b"], [(1, 2)], ["a"], [(1,)]))

    def test_row_count_must_match(self):
        self.assertFalse(self.ok(["a"], [(1,), (2,)], ["a"], [(1,)]))
        self.assertFalse(self.ok(["a"], [(1,)], ["a"], None))

    def test_order_only_matters_when_requested(self):
        self.assertTrue(self.ok(["a"], [(1,), (2,)], ["a"], [(2,), (1,)]))
        self.assertFalse(self.ok(["a"], [(1,), (2,)], ["a"], [(2,), (1,)], ordered=True))
        self.assertTrue(self.ok(["a"], [(1,), (2,)], ["a"], [(1,), (2,)], ordered=True))

    def test_strings_are_case_and_space_insensitive_and_none_is_handled(self):
        self.assertTrue(self.ok(["s"], [("SP",), (None,)], ["state"], [(" sp ",), (None,)]))


if __name__ == "__main__":
    unittest.main()
