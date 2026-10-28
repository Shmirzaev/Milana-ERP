"""Reproduce the refactor table/field inventory from an immutable Git revision.

Run with the backend dependency environment:
    python backend/scripts/build_refactor_inventory.py --repo . --ref <commit> --output <report.json>

Uses a fresh temporary git archive, static field discovery and offline SQLAlchemy
metadata. Never connects to a database or samples business values. This supports
current static mapped_column classes; unresolved ownership, duplicate classes and
AST/ORM mismatches fail. Discovery does not verify consumer typing or semantics.
"""
import ast
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import argparse
import tempfile


def build_inventory(repo: Path, revision: str, output: Path, destination: Path) -> None:
    archive = subprocess.check_output([
        'git', '-C', str(repo), 'archive', '--format=zip', revision,
        'backend/app', 'docs/REFACTOR_MAP.md', 'docs/TEAM_OWNERSHIP.md',
    ])
    with zipfile.ZipFile(io.BytesIO(archive)) as archive_file:
        assert all((destination / name).resolve().is_relative_to(destination.resolve())
                   for name in archive_file.namelist()), 'Unsafe archive entry'
        archive_file.extractall(destination)
    DEST = destination
    source_map = (DEST / 'docs/REFACTOR_MAP.md').read_text(encoding='utf-8')
    owners = dict(re.findall(r'^\| \[([A-Za-z0-9_]+)\]\([^\n]*?\) \| `[^`]+` \| `([^`]+)` \|', source_map, re.M))
    team = (DEST / 'docs/TEAM_OWNERSHIP.md').read_text(encoding='utf-8')
    engineers = {group: {'engineer': engineer.strip(), 'reviewer': reviewer.strip()}
        for group, engineer, reviewer in re.findall(r'^\| \[models/([^\]]+)\]\([^\n]*?\) \| ([^|]+) \| ([^|]+) \|', team, re.M)}
    engineers['support'] = {'engineer': 'Dilmurod', 'reviewer': 'Mirshoir', 'note': 'Shared helper coordination; domain policy still belongs to the feature owner.'}

    classes = {}
    source_hashes = {}
    paths = sorted((DEST / 'backend/app/schemas').rglob('*.py')) + [DEST / 'backend/app/db/base.py']
    for path in paths:
        relative = path.relative_to(DEST).as_posix()
        data = path.read_bytes()
        source_hashes[relative] = hashlib.sha256(data).hexdigest()
        tree = ast.parse(data.decode('utf-8-sig'))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            fields, table = {}, None
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in stmt.targets):
                    table = ast.literal_eval(stmt.value)
                if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                    continue
                value = stmt.value
                if not isinstance(value, ast.Call) or ast.unparse(value.func).split('.')[-1] != 'mapped_column':
                    continue
                name = stmt.target.id
                column_name = value.args[0].value if value.args and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str) else name
                fields[column_name] = {'attribute': name, 'source': relative, 'line': stmt.lineno,
                                       'annotation': ast.unparse(stmt.annotation), 'declaration': ast.unparse(value)}
            assert node.name not in classes, ('Duplicate class needs qualified resolution', node.name)
            classes[node.name] = {'table': table, 'fields': fields, 'bases': [ast.unparse(b).split('.')[-1] for b in node.bases], 'source': relative, 'line': node.lineno}

    def inherited_fields(name, seen=None):
        seen = set() if seen is None else set(seen)
        assert name not in seen, ('Inheritance cycle', name)
        seen.add(name)
        result = {}
        for base in classes[name]['bases']:
            if base in classes:
                result.update(inherited_fields(base, seen))
        result.update(classes[name]['fields'])
        return result

    # Import only ORM registration under an inert configuration. Fail closed if
    # future mapping imports attempt an Engine connection. No app.main/db.session.
    os.environ['ENV'] = 'test'
    from sqlalchemy.engine import Engine
    def refuse_connection(*args, **kwargs):
        raise RuntimeError('Inventory is offline: database connections are forbidden')
    Engine.connect = refuse_connection
    Engine.raw_connection = refuse_connection
    os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
    sys.path.insert(0, str(DEST / 'backend'))
    import app.schemas  # noqa: F401
    from app.db.base import Base
    assert 'app.main' not in sys.modules and 'app.db.session' not in sys.modules, 'Unexpected application/session import'
    from sqlalchemy import CheckConstraint, JSON, String, Text

    model_by_table = {c['table']: (name, c) for name, c in classes.items() if c['table']}
    assert len(model_by_table) == sum(bool(c['table']) for c in classes.values()), 'Duplicate mapped table'
    assert set(model_by_table) == set(Base.metadata.tables), {'ast_only': sorted(set(model_by_table) - set(Base.metadata.tables)), 'orm_only': sorted(set(Base.metadata.tables) - set(model_by_table))}

    def default_text(value):
        if value is None:
            return None
        arg = value.arg
        return getattr(arg, '__qualname__', str(arg)) if callable(arg) else str(arg)

    rows, missing_owners = [], []
    for table_name in sorted(model_by_table):
        class_name, definition = model_by_table[table_name]
        table = Base.metadata.tables[table_name]
        fields = inherited_fields(class_name)
        assert set(fields) == set(table.columns.keys()), (class_name, sorted(set(fields) ^ set(table.columns.keys())))
        owner = owners.get(class_name)
        if owner is None:
            missing_owners.append(class_name)
        checks = sorted(({'name': c.name, 'expression': str(c.sqltext)} for c in table.constraints if isinstance(c, CheckConstraint)), key=lambda item: (item['name'] or '', item['expression']))
        assignment = engineers.get(owner, {})
        assert assignment.get('engineer') and assignment.get('reviewer'), ('Missing engineering owner/reviewer', class_name, owner)
        columns = []
        for column in table.columns:
            related_checks = [c for c in checks if re.search(r'\b' + re.escape(column.name) + r'\b', c['expression'])]
            foreign_keys = sorted(f.target_fullname for f in column.foreign_keys)
            closed_hint = any(re.search(r'\b' + re.escape(column.name) + r'\s+IN\s*\(', c['expression'], re.I) for c in related_checks)
            semantic_hint = bool(re.search(r'(^|_)(status|type|kind|category|action|source|section|mode|stage|unit|factory|department)(_|$)', column.name))
            if closed_hint:
                classification = 'CLOSED_CHECK_RECONCILE_ENUM'
            elif foreign_keys:
                classification = 'REFERENCE_REVIEW_NOT_AUTOMATIC_ENUM'
            elif isinstance(column.type, JSON):
                classification = 'STRUCTURED_KEYS_VALUES_REVIEW'
            elif isinstance(column.type, (String, Text)):
                classification = 'FIXED_VOCABULARY_CANDIDATE' if semantic_hint else 'TEXT_SEMANTICS_REVIEW'
            else:
                classification = 'SCALAR_CONTRACT_REVIEW'
            columns.append(dict(name=column.name, **fields[column.name], sql_type=str(column.type),
                nullable=column.nullable, primary_key=column.primary_key, unique=column.unique,
                default=default_text(column.default), server_default=default_text(column.server_default),
                foreign_keys=foreign_keys, checks=related_checks, discovery_classification=classification,
                semantic_review='PENDING', actual_database_values='NOT_READ', consumer_migration='PENDING'))
        rows.append({'table': table_name, 'class': class_name, 'source': definition['source'], 'line': definition['line'],
                     'domain': owner or 'UNRESOLVED', 'assignment': engineers.get(owner, {}), 'checks': checks, 'columns': columns,
                     'operation_writer_trace': 'PENDING', 'verification': 'NOT_VERIFIED'})

    assert not missing_owners, ('Source map missing ownership', missing_owners)
    counts = Counter(column['discovery_classification'] for row in rows for column in row['columns'])
    report = {'source_revision': revision, 'scope': 'All ORM tables/columns in immutable integrated candidate; no DB connections or value sampling.',
              'validation': 'AST table/column sets, including inherited mixins, exactly match registered SQLAlchemy metadata.',
              'table_count': len(rows), 'column_count': sum(len(row['columns']) for row in rows),
              'discovery_classifications': dict(counts), 'domain_table_counts': dict(sorted(Counter(r['domain'] for r in rows).items())),
              'limitations': ['Discovery is not semantic approval or completed enum coverage.',
                             'Migration-only/unmapped database objects and actual stored values require separate database reconciliation.',
                             'DTOs, service parameters, JSON discriminators and alternate callers require operation-level tracing.',
                             'The selected Git revision is source discovery, not deployed-production verification.',
                             'Static mapped_column classes and known inheritance are supported; duplicate class names, unresolved ownership or AST/ORM mismatches fail.',
                             'Non-persisted input/update/output, query/action, internal and JSON discriminator contracts need a separate consumer ledger.'],
              'source_hashes': source_hashes, 'tables': rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    print(json.dumps({'source_revision': revision, 'tables': report['table_count'], 'columns': report['column_count'], 'domains': len(report['domain_table_counts']), 'output': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True, help='Git repository path')
    parser.add_argument('--ref', required=True, help='Committed source revision to inspect')
    parser.add_argument('--output', type=Path, required=True, help='Generated JSON report path')
    args = parser.parse_args()
    repo = args.repo.resolve()
    revision = subprocess.check_output([
        'git', '-C', str(repo), 'rev-parse', '--verify', args.ref + '^{commit}',
    ], text=True).strip()
    with tempfile.TemporaryDirectory(prefix='milana-inventory-') as temporary:
        snapshot = Path(temporary).resolve()
        assert snapshot.parent == Path(tempfile.gettempdir()).resolve()
        assert snapshot.name.startswith('milana-inventory-')
        build_inventory(repo, revision, args.output.resolve(), snapshot)


if __name__ == '__main__':
    main()
