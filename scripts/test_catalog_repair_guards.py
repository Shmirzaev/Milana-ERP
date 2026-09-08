import unittest
from catalog_repair_guards import validate_revision, validate_photo_source


class RepairGuards(unittest.TestCase):
    def test_old_manifest_cannot_silently_run_on_new_schema(self):
        validate_revision({}, '0113_variant_selling_price')
        with self.assertRaises(AssertionError):
            validate_revision({}, '0114_warehouse_stocktake')
        validate_revision({'database_revision': '0114_warehouse_stocktake'}, '0114_warehouse_stocktake')
        with self.assertRaises(AssertionError):
            validate_revision({'database_revision': 'unknown'}, 'unknown')

    def test_frozen_rejected_source_manifests_cannot_be_reapplied(self):
        for sid in ('1269', '1204'):
            with self.assertRaises(AssertionError):
                validate_photo_source({'model_no': 'XJ3001', 'source': {'id': sid}}, 'old_erp_model_original')
        for sid in ('shared-mediamessage-4916', 'shared-mediamessage-10201'):
            with self.assertRaises(AssertionError):
                validate_photo_source({'source': {'id': sid}}, 'telegram_original')
        validate_photo_source({'model_no': 'B3189', 'source': {'id': '430'}}, 'old_erp_model_original')
