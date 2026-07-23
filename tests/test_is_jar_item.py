import unittest

from app import is_jar_item


class IsJarItemTests(unittest.TestCase):
    def test_10_and_20_ltr_products_with_trailing_invoice_text_are_jars(self):
        for description in (
            "Bisleri Water 20LTR 01 (MRP 100)",
            "Bisleri Water 10LTR 09 (MRP 270)",
        ):
            with self.subTest(description=description):
                self.assertTrue(is_jar_item(description))

    def test_non_jar_sizes_and_embedded_larger_sizes_are_cases(self):
        for description in (
            "Bisleri Water 2LTR 09",
            "Bisleri Water 1LTR 12",
            "110LTR",
            "120LTR",
        ):
            with self.subTest(description=description):
                self.assertFalse(is_jar_item(description))


if __name__ == "__main__":
    unittest.main()
