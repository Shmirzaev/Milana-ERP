"""Fast deterministic tests: no production requests or real waiting."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from observe_release import ENDPOINTS, observe, probe_endpoint


class Clock:
    def __init__(self):
        self.now = 0

    def read(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.clock = Clock()
        self.output = Path(self.directory.name) / "observation.json"
        self.calls = []

    def probe(self, url, method):
        self.calls.append((url, method))
        return 200

    def run_observer(self, **overrides):
        args = dict(
            release="20260905_044515", commit="a" * 40, output=self.output,
            probe=self.probe, clock=self.clock.read, sleep=self.clock.sleep,
            emit=lambda message: None,
        )
        args.update(overrides)
        return observe(**args)

    def test_default_is_full_30_minutes(self):
        result = self.run_observer()
        self.assertEqual(result["elapsed_seconds"], 1800)
        self.assertEqual(len(result["checks"]), 61)
        self.assertEqual(len(self.calls), 244)
        self.assertEqual(result["status"], "health_checks_passed")
        self.assertTrue(result["closing_checks_required"])
        self.assertEqual(json.loads(self.output.read_text()), result)

    def test_reviewed_low_risk_is_10_minutes(self):
        result = self.run_observer(risk="low", reason="Reviewed isolated display wording")
        self.assertEqual(result["elapsed_seconds"], 600)
        self.assertEqual(len(result["checks"]), 21)
        self.assertEqual(self.calls[:4], [(url, method) for _, url, method in ENDPOINTS])

    def test_low_risk_without_reason_rejected_before_requests(self):
        with self.assertRaisesRegex(ValueError, "review reason"):
            self.run_observer(risk="low", reason=" ")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.output.exists())

    def test_failure_cannot_be_erased_by_recovery(self):
        calls = iter([503] + [200] * 100)
        result = self.run_observer(risk="low", reason="Small display change", probe=lambda *_: next(calls))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["elapsed_seconds"], 600)

    def test_interruption_is_not_success(self):
        def interrupt(seconds):
            raise KeyboardInterrupt
        result = self.run_observer(sleep=interrupt)
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(json.loads(self.output.read_text())["status"], "interrupted")

    def test_missed_interval_fails_instead_of_catching_up(self):
        result = self.run_observer(sleep=lambda seconds: self.clock.sleep(seconds + 1800))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failures"][0]["check"], "monitoring_gap")
        self.assertEqual(len(result["checks"]), 1)

    def test_early_sleep_return_does_not_shorten_window(self):
        result = self.run_observer(
            risk="low", reason="Small display change",
            sleep=lambda seconds: self.clock.sleep(min(seconds, 5)),
        )
        self.assertEqual(result["elapsed_seconds"], 600)
        self.assertEqual(result["status"], "health_checks_passed")

    def test_existing_evidence_preserved(self):
        self.output.write_text("previous evidence")
        with self.assertRaises(FileExistsError):
            self.run_observer()
        self.assertEqual(self.output.read_text(), "previous evidence")
        self.assertEqual(self.calls, [])

    def test_unexpected_error_persisted(self):
        def broken_probe(*args):
            raise RuntimeError("test failure")
        with self.assertRaises(RuntimeError):
            self.run_observer(probe=broken_probe)
        self.assertEqual(json.loads(self.output.read_text())["status"], "observer_error")

    def test_invalid_identity_rejected(self):
        for override in ({"release": "old"}, {"commit": "abc"}, {"risk": "unknown"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.run_observer(**override)
        self.assertEqual(self.calls, [])

    def test_network_and_redirect_errors_are_failures(self):
        for error, expected in (
            (HTTPError("https://example.test", 302, "redirect", {}, None), 302),
            (URLError("unreachable"), "URLError"),
        ):
            with patch("observe_release.urllib.request.build_opener") as opener:
                opener.return_value.open.side_effect = error
                self.assertEqual(probe_endpoint("https://example.test", "GET"), expected)


if __name__ == "__main__":
    unittest.main()
