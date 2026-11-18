"""Independent source controls for the owner-reviewed opening-stock manifest."""
import importlib.util
from decimal import Decimal
from pathlib import Path
import unittest

PATH = Path(__file__).with_name("build_accessories_opening_20261118.py")
SPEC = importlib.util.spec_from_file_location("accessories_builder", PATH)
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class SourceControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = BUILDER.build()
        cls.rows = {r["source_key"]: r for r in cls.manifest["rows"]}

    def test_complete_source_coverage_and_no_phantom_photo_stock(self):
        self.assertEqual(len(self.manifest["sources"]), 11)
        self.assertEqual(len(self.manifest["rows"]), 875)
        self.assertEqual(sum(r["family_code"] == "LAC" for r in self.rows.values()), 120)
        self.assertFalse(any(r["family_code"] == "LAC" and r["source_row"] > 123 for r in self.rows.values()))

    def test_current_cards_only_and_net_quantity(self):
        older = [r for r in self.rows.values() if r["family_code"] == "TAG" and r["source_sheet"] == "КАРТАЛАР"]
        current = [r for r in self.rows.values() if r["family_code"] == "TAG" and r["status"] == "ready"]
        self.assertEqual(len(older), 20)
        self.assertTrue(all(r["status"] == "historical_excluded" and "sku" not in r for r in older))
        self.assertEqual(len(current), 12)
        self.assertEqual(sum(Decimal(r["quantity"]) for r in current), Decimal(1442200))

    def test_elastic_uses_remaining_kg_and_shared_product_separate_batches(self):
        first, second = self.rows["ELA:1:7"], self.rows["ELA:1:11"]
        self.assertEqual((first["quantity"], second["quantity"]), ("258.0000", "450.0000"))
        self.assertEqual(first["sku"], second["sku"])
        self.assertNotEqual(first["batch_no"], second["batch_no"])
        self.assertEqual(first["unit"], "kg")

    def test_pack_units_and_button_size_decisions(self):
        self.assertEqual(self.rows["TPB:1:32"]["quantity"], "180.0000")
        self.assertEqual(self.rows["TPB:1:32"]["unit"], "bundle")
        self.assertIn("48 L", self.rows["BTN:1:4"]["name"])
        self.assertIn("11.3 мм", self.rows["BTN:1:93"]["name"])
        self.assertIn("Пуговица — Металл", self.rows["MET:1:12"]["name"])

    def test_unknown_quantity_and_pairs_cannot_create_stock(self):
        for key in ("MET:1:27", "LPC:1:4", "LPC:1:5", "LPC:1:9", "LPC:1:15", "LPC:1:17"):
            self.assertEqual(self.rows[key]["status"], "pending")
            self.assertNotIn("sku", self.rows[key])

    def test_duplicate_designs_are_pending_and_coded_thread_lots_are_retained(self):
        for key in ("LAC:1:29", "LAC:1:30", "ZIP:1:90", "ZIP:1:93", "BTN:1:23", "BTN:1:28", "BAG:1:14", "BAG:1:22", "TAP:1:18", "TAP:1:28"):
            self.assertEqual(self.rows[key]["status"], "pending")
        self.assertEqual(self.rows["THR:1:139"]["sku"], self.rows["THR:1:224"]["sku"])
        self.assertEqual(self.rows["THR:1:139"]["quantity"], "120.0000")
        self.assertEqual(self.rows["THR:1:224"]["status"], "zero_balance")
        self.assertEqual(self.rows["TAP:1:43"]["sku"], self.rows["TAP:1:51"]["sku"])

    def test_source_totals_reconcile_independently_per_unit_family(self):
        expected = {"LPC": "67650", "LAC": "453087.5", "ELA": "2260", "THR": "22296", "TAP": "288684.84", "BAG": "11869", "TPB": "15975", "MET": "416100", "ZIP": "170900", "BTN": "5792900"}
        for code, total in expected.items():
            actual = sum(Decimal(r["quantity"]) for r in self.rows.values() if r["family_code"] == code)
            self.assertEqual(actual, Decimal(total), code)

    def test_formula_evaluator_refuses_executable_content(self):
        for expression in ("=__import__('os').getcwd()", "=SUM(A1:A2)", "=A1.__class__", "='123'"):
            with self.assertRaises(ValueError):
                BUILDER.evaluator({"A1": expression})("A1")
        with self.assertRaises(ValueError):
            BUILDER.evaluator({"A1": "=B1", "B1": "=A1"})("A1")
        self.assertEqual(BUILDER.evaluator({"A1": 10, "A2": "=+A1*2-3"})("A2"), Decimal(17))


if __name__ == "__main__":
    unittest.main()
