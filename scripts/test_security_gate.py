"""Security gate trust boundaries, acceptance expiry and release/event wiring."""
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from security_gate import REPORTS, evaluate, requires_scan

ROOT = Path(__file__).resolve().parents[1]


def vulnerability(**changes):
    return {'VulnerabilityID': 'CVE-2099-0001', 'PkgName': 'example', 'PkgID': 'example@1',
            'InstalledVersion': '1', 'Severity': 'HIGH', 'FixedVersion': '2', 'Status': 'fixed', **changes}


class SecurityGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = self.root/'accepted.json'
        self.entries = []
        self.source = self.root/'source'
        (self.source/'backend').mkdir(parents=True)
        (self.source/'backend/requirements.txt').write_text('example==1\n')
        (self.source/'frontend').mkdir()
        (self.source/'frontend/package-lock.json').write_text('{}')
        for filename in REPORTS:
            self.report(filename, [])

    def report(self, name, vulnerabilities, *, target='frontend/package-lock.json', kind='npm', dev=True):
        packages = [{'ID': 'example@1', 'Name': 'example', 'Version': '1', 'Dev': dev}]
        result = {'Target': target, 'Type': kind, 'Vulnerabilities': vulnerabilities, 'Packages': packages}
        if name == 'backend-image.json':
            rows = [{'Target': 'debian', 'Type': 'debian', 'Packages': packages},
                    {'Target': 'Python', 'Type': 'python-pkg', 'Packages': packages}, result]
        elif name == 'frontend-image.json':
            rows = [{'Target': 'alpine', 'Type': 'alpine', 'Packages': packages},
                    {'Target': 'Node.js', 'Type': 'node-pkg', 'Packages': [{'Name': 'next'}]}, result]
        else:
            rows = [{'Target': 'backend/requirements.txt', 'Type': 'pip', 'Packages': packages}, result]
        (self.root/name).write_text(json.dumps({'SchemaVersion': 2, 'Results': rows}))

    def acceptance(self, **changes):
        entry = {'scope': 'dependencies:frontend/package-lock.json', 'type': 'npm', 'package': 'example',
                 'version': '1', 'advisories': ['CVE-2099-0001'], 'reason': 'reviewed bounded risk',
                 'accepted_by': 'Dilmurod', 'accepted_on': '2026-11-03', 'review_by': '2027-02-03',
                 'source': 'https://github.com/Shmirzaev/Milana-ERP/pull/362', **changes}
        self.entries.append(entry)

    def evaluate(self):
        self.policy.write_text(json.dumps({'schema_version': 1, 'findings': self.entries}))
        return evaluate(self.root, self.policy, date(2026, 11, 5), self.source)

    def test_each_fixed_high_and_critical_is_blocked(self):
        for severity in ('HIGH', 'CRITICAL'):
            for filename in REPORTS:
                with self.subTest(severity=severity, report=filename):
                    self.report(filename, [vulnerability(Severity=severity)])
                    self.assertFalse(self.evaluate()['passed'])
                    self.report(filename, [])

    def test_medium_is_visible_but_does_not_block(self):
        self.report('dependencies.json', [vulnerability(Severity='MEDIUM')])
        result = self.evaluate()
        self.assertTrue(result['passed'])
        self.assertEqual(result['findings'][0]['disposition'], 'below-threshold')

    def test_unfixed_findings_remain_visible_under_fix_available_rule(self):
        self.report('backend-image.json', [vulnerability(FixedVersion='', Status='affected')])
        result = self.evaluate()
        self.assertTrue(result['passed'])
        self.assertEqual(result['findings'][0]['disposition'], 'unfixed')
        self.assertEqual(result['counts']['backend-image.json']['HIGH'], 1)

    def test_status_fixed_without_version_fails_closed(self):
        self.report('backend-image.json', [vulnerability(FixedVersion='')])
        self.assertFalse(self.evaluate()['passed'])

    def test_explicit_acceptance_is_scoped_and_version_bound(self):
        self.acceptance()
        self.report('dependencies.json', [vulnerability()])
        self.assertTrue(self.evaluate()['passed'])
        self.report('dependencies.json', [vulnerability(InstalledVersion='1.1')])
        self.assertFalse(self.evaluate()['passed'])
        self.report('dependencies.json', [])
        self.report('frontend-image.json', [vulnerability()])
        self.assertFalse(self.evaluate()['passed'])

    def test_expired_acceptance_cannot_suppress_a_finding(self):
        self.acceptance(review_by='2026-11-04')
        self.report('dependencies.json', [vulnerability()])
        self.assertFalse(self.evaluate()['passed'])

    def test_development_acceptance_never_covers_runtime_or_unknown_relationship(self):
        self.acceptance(development_only=True)
        self.report('dependencies.json', [vulnerability()], dev=True)
        self.assertTrue(self.evaluate()['passed'])
        self.report('dependencies.json', [vulnerability()], dev=False)
        self.assertFalse(self.evaluate()['passed'])
        report = json.loads((self.root/'dependencies.json').read_text())
        next(r for r in report['Results'] if r['Target'] == 'frontend/package-lock.json')['Packages'] = []
        (self.root/'dependencies.json').write_text(json.dumps(report))
        with self.assertRaises(ValueError): self.evaluate()

    def test_unfixed_os_acceptance_stops_matching_when_a_fix_appears(self):
        self.acceptance(scope='backend-image', type='debian', only_unfixed=True)
        self.report('backend-image.json', [vulnerability(FixedVersion='', Status='affected')], kind='debian')
        self.assertEqual(self.evaluate()['findings'][0]['disposition'], 'accepted')
        self.report('backend-image.json', [vulnerability()], kind='debian')
        self.assertFalse(self.evaluate()['passed'])

    def test_advisory_alias_matches_approved_minimatch_advisory(self):
        self.acceptance(advisories=['GHSA-approved'])
        self.report('dependencies.json', [vulnerability(VendorIDs=['GHSA-approved'])])
        self.assertTrue(self.evaluate()['passed'])

    def test_accepted_dev_target_cannot_hide_same_package_in_another_lockfile(self):
        self.acceptance(development_only=True)
        self.report('dependencies.json', [vulnerability()])
        path = self.root/'dependencies.json'
        report = json.loads(path.read_text())
        runtime = {**next(r for r in report['Results'] if r['Target'] == 'frontend/package-lock.json'), 'Target': 'other/package-lock.json',
                   'Packages': [{'ID': 'example@1', 'Dev': False}]}
        report['Results'].append(runtime)
        path.write_text(json.dumps(report))
        result = self.evaluate()
        self.assertFalse(result['passed'])
        self.assertEqual(result['counts']['dependencies.json']['HIGH'], 1)

    def test_duplicate_metadata_does_not_inflate_counts(self):
        self.report('backend-image.json', [vulnerability(), vulnerability()])
        self.assertEqual(self.evaluate()['counts']['backend-image.json']['HIGH'], 1)

    def test_missing_malformed_reports_and_blanket_acceptances_fail_closed(self):
        (self.root/'frontend-image.json').unlink()
        with self.assertRaises(FileNotFoundError): self.evaluate()
        (self.root/'frontend-image.json').write_text('{}')
        with self.assertRaises(ValueError): self.evaluate()
        self.report('frontend-image.json', [])
        self.acceptance(package='*')
        with self.assertRaises(ValueError): self.evaluate()

    def test_empty_reports_and_missing_required_analyzers_fail_closed(self):
        for filename in REPORTS:
            original = (self.root/filename).read_text()
            (self.root/filename).write_text(json.dumps({'SchemaVersion': 2, 'Results': []}))
            with self.assertRaises(ValueError): self.evaluate()
            (self.root/filename).write_text(original)
        report = json.loads((self.root/'dependencies.json').read_text())
        report['Results'] = [r for r in report['Results'] if r['Target'] != 'frontend/package-lock.json']
        (self.root/'dependencies.json').write_text(json.dumps(report))
        with self.assertRaises(ValueError): self.evaluate()

    def test_triggers_are_narrow_and_integration_pushes_are_retained(self):
        for event in ('schedule', 'workflow_dispatch'):
            self.assertTrue(requires_scan(event, 'refs/heads/clone_main', []))
        for ref in ('main', 'clone_main'):
            self.assertTrue(requires_scan('push', 'refs/heads/'+ref, []))
        self.assertFalse(requires_scan('push', 'refs/heads/codex/ordinary', ['backend/Dockerfile']))
        for path in ('backend/Dockerfile', 'scripts/rf013_frontend.Dockerfile', 'backend/requirements-dev.txt',
                     'frontend/package-lock.json', 'frontend/pnpm-lock.yaml', 'poetry.lock'):
            self.assertTrue(requires_scan('pull_request', '', [path]), path)
        for path in ('backend/app/api/routes/admin.py', 'docs/README.md', '.github/workflows/ci.yml'):
            self.assertFalse(requires_scan('pull_request', '', [path]), path)

    def test_release_needs_scan_and_publishes_identical_images_without_rebuilding(self):
        workflow = yaml.load((ROOT/'.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
        release = workflow['jobs']['release']
        self.assertIn('security-scan', release['needs'])
        self.assertIn('!inputs.security_scan_only', release['if'])
        text = json.dumps(release)
        self.assertIn('identity.json', text)
        self.assertIn("identity['source_sha'] == os.environ['GITHUB_SHA']", text)
        self.assertNotIn('docker/build-push-action', text)
        self.assertIn('docker load', text)
        self.assertIn('docker push', text)

    def test_scanner_database_and_concurrency_are_pinned_and_safe(self):
        ci = yaml.load((ROOT/'.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
        scan = yaml.load((ROOT/'.github/workflows/security-scan.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(scan['jobs']['scan']['env']['TRIVY_VERSION'], '0.76.1')
        self.assertIn('schedule', ci['on'])
        self.assertEqual(ci['concurrency']['cancel-in-progress'], "${{ github.event_name == 'pull_request' }}")
        self.assertIn('github.run_id', ci['concurrency']['group'])
        branches = ci['on']['push']['branches']
        self.assertNotIn('codex/**', branches)
        self.assertIn('codex/ismail-finance-pilot-20261025', branches)
        text = (ROOT/'.github/workflows/security-scan.yml').read_text()
        self.assertIn('actions/cache@v4', text)
        self.assertIn('--include-dev-deps', text)
        self.assertIn('--skip-db-update', text)
        self.assertNotIn('--ignore-unfixed', text)


if __name__ == '__main__':
    unittest.main()
