import unittest

from pricing import discounted_price


class PricingTests(unittest.TestCase):
    def test_discount_is_subtracted(self):
        self.assertAlmostEqual(discounted_price(200, 10), 180)

    def test_no_discount(self):
        self.assertEqual(discounted_price(80, 0), 80)

    def test_full_discount(self):
        self.assertEqual(discounted_price(80, 100), 0)

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            discounted_price(10, 110)
