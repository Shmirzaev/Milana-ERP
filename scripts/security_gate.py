"""Evaluate complete Trivy reports; accepted risks remain visible in the output."""
import argparse
from collections import Counter
from datetime import date
import json
import os
import re
from pathlib import Path

REPORTS = ('backend-image.json', 'frontend-image.json', 'dependencies.json')
SEVERITIES = {'UNKNOWN', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}


def requires_scan(event, ref, paths):
    if event in {'schedule', 'workflow_dispatch'}:
        return True
    if event == 'push':
        return ref in {'refs/heads/main', 'refs/heads/clone_main'}
    if event == 'pull_request':
        return any(Path(path).name.startswith('Dockerfile')
                   or (Path(path).name.startswith('requirements') and Path(path).suffix in {'.txt', '.in'})
                   or Path(path).name.endswith(('.Dockerfile', '.lock', '-lock.json', '.lockb'))
                   or Path(path).name in {'npm-shrinkwrap.json', 'pnpm-lock.yaml'} for path in paths)
    return False


def load_acceptances(path):
    document = json.loads(path.read_text())
    if document.get('schema_version') != 1 or not isinstance(document.get('findings'), list):
        raise ValueError('Invalid accepted-findings document')
    for entry in document['findings']:
        for key in ('scope', 'type', 'package', 'version', 'reason', 'accepted_by', 'source'):
            if not isinstance(entry.get(key), str) or not entry[key].strip() or '*' in entry[key]:
                raise ValueError(f'Invalid acceptance {key}')
        if not entry.get('advisories') or any(not isinstance(i, str) or '*' in i for i in entry['advisories']):
            raise ValueError('Acceptance must list exact advisory IDs')
        for key in ('only_unfixed', 'development_only'):
            if key in entry and not isinstance(entry[key], bool):
                raise ValueError(f'Invalid acceptance {key}')
        if date.fromisoformat(entry['review_by']) <= date.fromisoformat(entry['accepted_on']):
            raise ValueError('Review date must follow acceptance')
    return document['findings']


def accepted(finding, result, scope, entries, today):
    aliases = {finding['VulnerabilityID'], *(finding.get('VendorIDs') or [])}
    for entry in entries:
        if (entry['scope'] != scope or entry['type'] != result['Type']
                or entry['package'] != finding['PkgName'] or entry['version'] != finding['InstalledVersion']
                or not aliases.intersection(entry['advisories'])
                or date.fromisoformat(entry['review_by']) < today):
            continue
        if entry.get('only_unfixed') and (finding.get('FixedVersion') or finding.get('Status') == 'fixed'):
            continue
        if entry.get('development_only'):
            packages = [p for p in result.get('Packages', []) if p.get('ID') == finding.get('PkgID')]
            if not packages or not all(p.get('Dev') is True for p in packages):
                continue
        return entry
    return None


def check_inventory(filename, results, source_root):
    populated = [row for row in results if row.get('Packages')]
    types = {row.get('Type') for row in populated}
    if filename == 'backend-image.json':
        if not {'debian', 'python-pkg'} <= types:
            raise ValueError('Backend OS/Python inventories are missing')
        expected = {re.split(r'[=<>!~\[]', line.strip(), maxsplit=1)[0].lower().replace('_', '-')
                    for line in (source_root/'backend/requirements.txt').read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith(('#', '-'))}
        found = {p.get('Name', '').lower().replace('_', '-') for row in populated
                 if row.get('Type') == 'python-pkg' for p in row['Packages']}
        if expected - found:
            raise ValueError(f'Backend Python packages missing: {sorted(expected - found)}')
    elif filename == 'frontend-image.json':
        if not {'alpine', 'node-pkg'} <= types or not any(
                p.get('Name') == 'next' for row in populated for p in row['Packages']):
            raise ValueError('Frontend OS/Next.js inventories are missing')
    else:
        expected = {p.relative_to(source_root).as_posix() for p in source_root.rglob('requirements*.txt')
                    if not {'.git', 'node_modules', '.venv'}.intersection(p.parts)}
        expected.add('frontend/package-lock.json')
        found = {row.get('Target') for row in populated}
        if expected - found:
            raise ValueError(f'Dependency files not scanned: {sorted(expected - found)}')


def evaluate(report_dir, policy, today=None, source_root=None):
    source_root = source_root or Path(__file__).resolve().parents[1]
    entries = load_acceptances(policy)
    today = today or date.today()
    summaries, findings = {}, []
    for filename in REPORTS:
        report = json.loads((report_dir / filename).read_text())
        if report.get('SchemaVersion') != 2 or not isinstance(report.get('Results'), list):
            raise ValueError(f'Invalid or incomplete Trivy report: {filename}')
        check_inventory(filename, report['Results'], source_root)
        counts, seen = Counter(), set()
        for result in report['Results']:
            if not result.get('Target') or not result.get('Type'):
                raise ValueError(f'Missing scanned target/type in {filename}')
            scope = f'dependencies:{result["Target"]}' if filename == 'dependencies.json' else filename.removesuffix('.json')
            for finding in result.get('Vulnerabilities') or []:
                for key in ('VulnerabilityID', 'PkgName', 'InstalledVersion', 'Severity'):
                    if not isinstance(finding.get(key), str) or not finding[key]:
                        raise ValueError(f'Invalid vulnerability {key} in {filename}')
                if finding['Severity'] not in SEVERITIES:
                    raise ValueError('Unknown severity')
                key = (result['Type'], finding['PkgName'], finding['InstalledVersion'], finding['VulnerabilityID'])
                if key not in seen:
                    counts[finding['Severity']] += 1
                    seen.add(key)
                match = accepted(finding, result, scope, entries, today)
                fixable = bool(finding.get('FixedVersion')) or finding.get('Status') == 'fixed'
                blocked = finding['Severity'] in {'HIGH', 'CRITICAL'} and fixable and match is None
                disposition = 'blocked' if blocked else 'accepted' if match else 'unfixed' if not fixable else 'below-threshold'
                findings.append({'report': filename, 'target': result['Target'], 'type': result['Type'],
                                 'package': finding['PkgName'], 'version': finding['InstalledVersion'],
                                 'advisory': finding['VulnerabilityID'], 'severity': finding['Severity'],
                                 'fixed_version': finding.get('FixedVersion', ''), 'disposition': disposition})
        summaries[filename] = {severity: counts[severity] for severity in sorted(SEVERITIES)}
    blocked = [row for row in findings if row['disposition'] == 'blocked']
    return {'passed': not blocked, 'counts': summaries, 'blocked': blocked, 'findings': findings}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scope', action='store_true')
    parser.add_argument('--changed-files', type=Path)
    parser.add_argument('--reports', type=Path)
    parser.add_argument('--accepted', type=Path, default=Path('security/accepted-findings.json'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source-root', type=Path, default=Path('.'))
    args = parser.parse_args()
    if args.scope:
        paths = args.changed_files.read_text().splitlines() if args.changed_files else []
        required = requires_scan(os.environ['GITHUB_EVENT_NAME'], os.environ['GITHUB_REF'], paths)
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
            out.write(f'required={str(required).lower()}\n')
        return 0
    if not args.reports or not args.output:
        parser.error('--reports and --output are required')
    result = evaluate(args.reports, args.accepted, source_root=args.source_root)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'passed': result['passed'], 'counts': result['counts'], 'blocked': result['blocked']}, indent=2))
    return int(not result['passed'])


if __name__ == '__main__':
    raise SystemExit(main())
