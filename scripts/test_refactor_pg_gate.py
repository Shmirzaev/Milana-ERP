"""Offline red/green checks for missing or skipped required PG evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import run_refactor_pg_gate as gate


class RequiredPGGateTests(unittest.TestCase):
    def setUp(self):
        # Avoid changing global tmp settings; these tests never touch a database.
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)

    def report(self):
        tree = ET.Element('testsuites')
        suite = ET.SubElement(tree, 'testsuite')
        for module, names in gate.REQUIRED_CASES.items():
            for name in names:
                ET.SubElement(suite, 'testcase', classname=f'app.tests.{module}', name=name)
        return tree

    def write_report(self, tree):
        path = self.root / 'report.xml'
        ET.ElementTree(tree).write(path)
        return path

    def test_complete_evidence_passes(self):
        counts = gate.check_report(self.write_report(self.report()))
        self.assertEqual(sum(counts.values()), 634)

    def test_stocktake_undo_cases_are_required_and_passing(self):
        module = "test_stocktake_undo_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 6)
        self.assertEqual(gate.GROUPS[module][0], 6)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_stocktake_scan_cases_are_required_and_passing(self):
        module = "test_stocktake_scan_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 5)
        self.assertEqual(gate.GROUPS[module][0], 5)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_manual_create_cases_are_required_and_passing(self):
        module = "test_waste_manual_create_commit_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 2)
        self.assertEqual(gate.GROUPS[module][0], 2)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_race_rollback_postgres_cases_are_required_and_passing(self):
        module = 'test_waste_race_rollback_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 2)
        self.assertEqual(gate.GROUPS[module][0], 2)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_sale_commit_postgres_cases_are_required_and_passing(self):
        module = 'test_waste_sale_commit_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 3)
        self.assertEqual(gate.GROUPS[module][0], 3)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_sale_list_postgres_cases_are_required_and_passing(self):
        module = 'test_waste_sale_list_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 4)
        self.assertEqual(gate.GROUPS[module][0], 4)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_test_price_calculation_purchasing_postgres_cases_are_required_and_passing(self):
        module = 'test_price_calculation_purchasing_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 2)
        self.assertEqual(gate.GROUPS[module][0], 2)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_test_price_calculation_status_postgres_cases_are_required_and_passing(self):
        module = 'test_price_calculation_status_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 1)
        self.assertEqual(gate.GROUPS[module][0], 1)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_price_creation_postgres_cases_are_required_and_passing(self):
        module = 'test_price_calculation_creation_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 8)
        self.assertEqual(gate.GROUPS[module][0], 8)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_model_delete_postgres_cases_are_required_and_passing(self):
        module = 'test_model_delete_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 14)
        self.assertEqual(gate.GROUPS[module][0], 14)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_accessory_price_postgres_cases_are_required_and_passing(self):
        module = 'test_price_calculation_accessory_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 3)
        self.assertEqual(gate.GROUPS[module][0], 3)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_cutting_price_postgres_cases_are_required_and_passing(self):
        module = 'test_price_calculation_cutting_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 3)
        self.assertEqual(gate.GROUPS[module][0], 3)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_price_calculation_finance_postgres_cases_are_required_and_passing(self):
        module = 'test_price_calculation_finance_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 4)
        self.assertEqual(gate.GROUPS[module][0], 4)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_modelsize_delete_postgres_cases_are_required_and_passing(self):
        module = 'test_modelsize_delete_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 8)
        self.assertEqual(gate.GROUPS[module][0], 8)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_model_create_postgres_cases_are_required_and_passing(self):
        module = 'test_model_create_commit_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 7)
        self.assertEqual(gate.GROUPS[module][0], 7)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_reject_postgres_cases_are_required_and_passing(self):
        module = 'test_waste_reject_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 17)
        self.assertEqual(gate.GROUPS[module][0], 17)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_approve_postgres_cases_are_required_and_passing(self):
        module = 'test_waste_approve_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 16)
        self.assertEqual(gate.GROUPS[module][0], 16)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_mark_disposed_postgres_cases_are_required_and_passing(self):
        module = 'test_waste_mark_disposed_postgres'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 15)
        self.assertEqual(gate.GROUPS[module][0], 15)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_disposal_integrity_cases_are_required_and_passing(self):
        module = 'test_waste_disposal_integrity'
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 4)
        self.assertEqual(gate.GROUPS[module][0], 4)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_waste_request_cases_are_required_and_passing(self):
        module = "test_waste_request_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 3)
        self.assertEqual(gate.GROUPS[module][0], 3)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "failure", "error"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        ET.SubElement(suite, "testcase", classname=case.get("classname"), name=name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_receipt_cases_are_required_and_cannot_be_skipped_or_replaced(self):
        for module, count in (("test_purchase_receipt_concurrency", 2),
                              ("test_purchase_receipt_idempotency", 3)):
            self.assertEqual(len(gate.REQUIRED_CASES[module]), count)
            self.assertEqual(gate.GROUPS[module][0], count)
            for name in gate.REQUIRED_CASES[module]:
                for mutation in ("skipped", "replacement"):
                    with self.subTest(module=module, name=name, mutation=mutation):
                        tree = self.report()
                        case = next(row for row in tree.iter("testcase")
                                    if row.get("classname") == f"app.tests.{module}"
                                    and row.get("name") == name)
                        if mutation == "skipped":
                            ET.SubElement(case, "skipped")
                        else:
                            case.set("name", "unrelated_replacement_case")
                        with self.assertRaises(ValueError):
                            gate.check_report(self.write_report(tree))

    def test_item_delete_cases_cannot_be_skipped_or_replaced(self):
        module = "test_item_delete_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 11)
        self.assertEqual(gate.GROUPS[module][0], 11)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("skipped", "replacement"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    case = next(row for row in tree.iter("testcase")
                                if row.get("classname") == f"app.tests.{module}"
                                and row.get("name") == name)
                    if mutation == "skipped":
                        ET.SubElement(case, "skipped")
                    else:
                        case.set("name", "unrelated_replacement_case")
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_process_qr_size_cases_cannot_be_skipped_or_replaced(self):
        module = "test_process_qr_size_setup_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 7)
        self.assertEqual(gate.GROUPS[module][0], 7)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("skipped", "replacement"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    case = next(row for row in tree.iter("testcase")
                                if row.get("classname") == f"app.tests.{module}"
                                and row.get("name") == name)
                    if mutation == "skipped":
                        ET.SubElement(case, "skipped")
                    else:
                        case.set("name", "unrelated_replacement_case")
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_model_image_delete_cases_cannot_be_skipped_or_replaced(self):
        module = "test_model_image_delete_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 5)
        self.assertEqual(gate.GROUPS[module][0], 5)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("skipped", "replacement"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    case = next(row for row in tree.iter("testcase")
                                if row.get("classname") == f"app.tests.{module}"
                                and row.get("name") == name)
                    if mutation == "skipped":
                        ET.SubElement(case, "skipped")
                    else:
                        case.set("name", "unrelated_replacement_case")
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_stocktake_create_each_case_rejects_missing_duplicate_and_nonpass(self):
        module = "test_stocktake_create_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 4)
        self.assertEqual(gate.GROUPS[module][0], 4)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("missing", "replacement", "duplicate", "skipped", "error", "failure"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    rows = [row for row in suite if row.get("classname") == f"app.tests.{module}"]
                    case = next(row for row in rows if row.get("name") == name)
                    if mutation == "missing":
                        suite.remove(case)
                    elif mutation == "replacement":
                        case.set("name", "unrelated_replacement_case")
                    elif mutation == "duplicate":
                        other = next(row for row in rows if row is not case)
                        other.set("name", name)
                    else:
                        ET.SubElement(case, mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_stocktake_delete_cases_cannot_be_skipped_or_replaced(self):
        module = "test_stocktake_delete_postgres"
        self.assertEqual(len(gate.REQUIRED_CASES[module]), 5)
        for name in gate.REQUIRED_CASES[module]:
            for mutation in ("skipped", "replacement"):
                with self.subTest(name=name, mutation=mutation):
                    tree = self.report()
                    case = next(row for row in tree.iter("testcase") if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                    if mutation == "skipped":
                        ET.SubElement(case, "skipped")
                    else:
                        case.set("name", "unrelated_replacement_case")
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_postgres_old_bearer_cutoff_missing_or_skipped_fails(self):
        module = "test_identity_admin_user_update"
        name = "test_password_change_rejects_old_bearer_and_accepts_new_bearer[postgres]"
        self.assertIn(name, gate.REQUIRED_CASES[module])
        for mutation in ("missing", "skipped"):
            with self.subTest(mutation=mutation):
                tree = self.report()
                suite = next(tree.iter("testsuite"))
                case = next(row for row in suite if row.get("classname") == f"app.tests.{module}" and row.get("name") == name)
                if mutation == "missing":
                    suite.remove(case)
                else:
                    ET.SubElement(case, "skipped")
                with self.assertRaises(ValueError):
                    gate.check_report(self.write_report(tree))

    def test_catalog_create_groups_have_exact_registered_case_counts(self):
        for module, count in (("test_modelsize_create_postgres", 2), ("test_modelcolor_create_postgres", 27)):
            with self.subTest(module=module):
                self.assertIn(module, gate.REQUIRED_CASES)
                self.assertEqual(len(gate.REQUIRED_CASES[module]), count)
                self.assertEqual(len(set(gate.REQUIRED_CASES[module])), count)

    def test_catalog_create_missing_duplicate_and_nonpass_cannot_fill_gate(self):
        for module in ("test_modelsize_create_postgres", "test_modelcolor_create_postgres"):
            for mutation in ("missing", "duplicate", "failure", "error", "skipped"):
                with self.subTest(module=module, mutation=mutation):
                    self.assertIn(module, gate.REQUIRED_CASES)
                    tree = self.report()
                    suite = next(tree.iter("testsuite"))
                    rows = [row for row in suite if row.get("classname") == f"app.tests.{module}"]
                    if mutation == "missing":
                        suite.remove(rows[0])
                    elif mutation == "duplicate":
                        rows[-1].set("name", rows[0].get("name"))
                    else:
                        ET.SubElement(rows[0], mutation)
                    with self.assertRaises(ValueError):
                        gate.check_report(self.write_report(tree))

    def test_skipped_failed_and_error_evidence_are_rejected(self):
        for tag in ('skipped', 'failure', 'error'):
            with self.subTest(tag=tag):
                tree = self.report()
                ET.SubElement(next(tree.iter('testcase')), tag)
                with self.assertRaisesRegex(ValueError, 'did not pass'):
                    gate.check_report(self.write_report(tree))

    def test_missing_group_and_case_fail(self):
        tree = self.report()
        suite = next(tree.iter('testsuite'))
        suite.remove(next(tree.iter('testcase')))
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            gate.check_report(self.write_report(tree))

    def test_missing_required_function_fails_even_with_same_total(self):
        tree = self.report()
        for case in tree.iter('testcase'):
            if case.get('name', '').startswith('test_pg_unknown_customer'):
                case.set('name', 'different_business_case')
        with self.assertRaisesRegex(ValueError, 'function missing'):
            gate.check_report(self.write_report(tree))

    def test_duplicate_cases_cannot_fill_count(self):
        tree = self.report()
        cases = list(tree.iter('testcase'))
        cases[1].attrib.update(cases[0].attrib)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            gate.check_report(self.write_report(tree))

    def test_unrelated_case_cannot_replace_any_required_case(self):
        for module in gate.REQUIRED_CASES:
            tree = self.report()
            selected = [case for case in tree.iter('testcase')
                        if case.get('classname') == f'app.tests.{module}']
            selected[0].set('name', 'unrelated_replacement_case')
            with self.subTest(module=module), self.assertRaises(ValueError):
                gate.check_report(self.write_report(tree))

    def test_one_rollback_parameter_cannot_replace_another(self):
        tree = self.report()
        for case in tree.iter('testcase'):
            if case.get('name') == 'test_pg_edit_and_audit_rollback_together_then_retry[audit_finalized]':
                case.set('name', 'test_pg_edit_and_audit_rollback_together_then_retry[unrelated]')
                break
        else:
            self.fail('frozen rollback parameter not present')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_additional_cases_are_allowed(self):
        tree = self.report()
        ET.SubElement(next(tree.iter('testsuite')), 'testcase',
                      classname='app.tests.test_bom_add_characterization', name='new_case')
        counts = gate.check_report(self.write_report(tree))
        self.assertEqual(counts['test_bom_add_characterization'], 55)

    def test_empty_and_malformed_evidence_fail(self):
        with self.assertRaisesRegex(ValueError, 'no test cases'):
            gate.check_report(self.write_report(ET.Element('testsuites')))
        path = self.root / 'malformed.xml'
        path.write_text('<testsuites>', encoding='utf-8')
        with self.assertRaises(ET.ParseError):
            gate.check_report(path)

    def test_required_config_is_checked_before_starting_pytest(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(gate.subprocess, 'run') as run:
            with patch('sys.argv', ['gate']), self.assertRaises(SystemExit) as error:
                gate.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_sanitization_removes_inherited_libpq_redirects_and_secrets(self):
        source = {"PGHOSTADDR": "10.0.0.1", "PGHOST": "other", "PGSERVICE": "remote",
                  "PGPASSWORD": "secret", "pgoptions": "-c search_path=public",
                  "MILANA_REQUIRE_TEST_PG": "1", "MILANA_TEST_PG_INSTANCE": "pinned", "PATH": "path"}
        clean = gate.sanitized_pg_environment(source, self.root)
        self.assertEqual({k for k in clean if k.upper().startswith("PG")}, {"PGPASSFILE", "PGSERVICEFILE"})
        self.assertEqual(clean["MILANA_TEST_PG_INSTANCE"], "pinned")
        self.assertEqual(clean["MILANA_REQUIRE_TEST_PG"], "1")
        self.assertEqual(Path(clean["PGPASSFILE"]).read_bytes(), b"")
        self.assertEqual(Path(clean["PGSERVICEFILE"]).read_bytes(), b"")

    def test_missing_brand_case_fails_even_if_other_group_has_extra(self):
        tree = self.report()
        suite = next(tree.iter('testsuite'))
        brand = next(case for case in tree.iter('testcase')
                     if case.get('classname') == 'app.tests.test_brand_create_postgres')
        suite.remove(brand)
        ET.SubElement(suite, 'testcase', classname='app.tests.test_bom_add_characterization', name='extra')
        with self.assertRaisesRegex(ValueError, 'expected at least'):
            gate.check_report(self.write_report(tree))

    def test_planning_rollback_boundary_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_planning_alternate_creation_postgres'
                    and case.get('name') ==
                    'test_pg_alternate_postflush_and_audit_failure_rollback_retry[log_action]')
        case.set('name', 'unrelated_replacement_case')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_customer_failure_point_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_customer_create_postgres'
                    and case.get('name') ==
                    'test_pg_route_failure_rolls_back_then_retry[audit_finalize]')
        case.set('name', 'test_pg_route_failure_rolls_back_then_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_brand_update_case_policy_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_brand_update_postgres'
                    and case.get('name') == 'test_pg_case_variant_update_is_allowed')
        case.set('name', 'unrelated_replacement_case')
        with self.assertRaises(ValueError):
            gate.check_report(self.write_report(tree))

    def test_supplier_commit_failure_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_supplier_create_postgres'
                    and case.get('name') == 'test_pg_route_failure_rolls_back_then_retry[commit]')
        case.set('name', 'test_pg_route_failure_rolls_back_then_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_customer_update_commit_case_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_customer_update_postgres'
                    and case.get('name') == 'test_pg_precommit_failure_rolls_back_and_retry[before_commit]')
        case.set('name', 'test_pg_precommit_failure_rolls_back_and_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_supplier_update_commit_case_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_supplier_update_postgres'
                    and case.get('name') == 'test_pg_precommit_failure_rolls_back_and_retry[before_commit]')
        case.set('name', 'test_pg_precommit_failure_rolls_back_and_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_customer_delete_commit_case_cannot_be_replaced(self):
        tree = self.report()
        case = next(case for case in tree.iter('testcase')
                    if case.get('classname') == 'app.tests.test_customer_delete_postgres'
                    and case.get('name') == 'test_pg_delete_precommit_failure_rolls_back_then_retry[before_commit]')
        case.set('name', 'test_pg_delete_precommit_failure_rolls_back_then_retry[unrelated]')
        with self.assertRaisesRegex(ValueError, 'case identities missing'):
            gate.check_report(self.write_report(tree))

    def test_shipment_reopen_source_pin_and_every_required_case_are_frozen(self):
        module = "test_shipment_reopen_invoice_postgres"
        manifest = json.loads(Path(gate.__file__).with_name("refactor_pg_required_cases.json").read_text(encoding="utf-8"))
        expected = (
            "test_pg_shipment_reopen_finance_participant_same_session_and_no_early_commit",
            "test_pg_shipment_reopen_preflights_every_invoice_before_any_finance_write",
            "test_pg_shipment_reopen_audit_failure_rolls_back_and_retry_commits_all",
            "test_pg_invoice_payment_and_shipment_reopen_serialize_on_invoice_row",
        )
        source = manifest["sources"][module]
        self.assertEqual(source["revision"], "bb00ca3921404fe8482f774752ee0d05db45c180")
        self.assertEqual(source["git_blob_sha256"], "e03a4da9b9da696ede2f908fa9a5b1f6d95fdad17fd77c310167c2950cd24f97")
        self.assertEqual(tuple(source["selected_functions"]), expected)
        self.assertEqual(tuple(manifest["cases"][module]), expected)
        self.assertEqual(gate.GROUPS[module], (4, expected))
        for mutation in ("missing", "duplicate", "failure", "error", "skipped"):
            with self.subTest(mutation=mutation):
                tree = self.report()
                suite = next(tree.iter("testsuite"))
                rows = [row for row in suite if row.get("classname") == f"app.tests.{module}"]
                if mutation == "missing":
                    suite.remove(rows[0])
                elif mutation == "duplicate":
                    rows[-1].set("name", rows[0].get("name"))
                else:
                    ET.SubElement(rows[0], mutation)
                with self.assertRaises(ValueError):
                    gate.check_report(self.write_report(tree))

    def test_bootstrap_only_ci_and_fixed_endpoint(self):
        identity = self.root / 'identity.json'
        env = self.root / 'github-env'
        identity.write_text(json.dumps({'system_identifier': '123456', 'server_version': '17.11',
                                        'data_directory': '/var/lib/postgresql/data'}), encoding='utf-8')
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, 'GitHub Actions'):
            gate.configure_ci(identity, env)
        self.assertFalse(env.exists())
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}, clear=True):
            gate.configure_ci(identity, env)
        values = dict(line.split('=', 1) for line in env.read_text().splitlines())
        config = json.loads(values['MILANA_TEST_PG_INSTANCE'])
        self.assertEqual(values['MILANA_REQUIRE_TEST_PG'], '1')
        self.assertEqual(config['host'], '127.0.0.1')
        self.assertEqual(config['port'], 55432)
        self.assertEqual(config['target_prefix'], 'review_ci_refactor_')

    def test_invalid_container_identity_fails_before_env_write(self):
        identity = self.root / 'identity.json'
        env = self.root / 'github-env'
        for changes in ({'system_identifier': 'invalid'}, {'server_version': '16.9'}, {'data_directory': 'relative'}):
            data = {'system_identifier': '123456', 'server_version': '17.11', 'data_directory': '/pgdata'}
            data.update(changes)
            identity.write_text(json.dumps(data), encoding='utf-8')
            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}, clear=True), self.assertRaises(ValueError):
                gate.configure_ci(identity, env)
            self.assertFalse(env.exists())


if __name__ == '__main__':
    unittest.main()
