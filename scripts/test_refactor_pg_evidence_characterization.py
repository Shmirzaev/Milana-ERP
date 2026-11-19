"""Runner contracts backed by actual disposable SQLite/PostgreSQL audit receipts."""
from decimal import Decimal
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, func, select
from sqlalchemy.orm import Session

import run_refactor_pg_gate as primary
import run_refactor_pg_supplement_gate as supplement

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
from app.db.base import Base
from app.models.audit_service import log_action, verify_audit_hash_chain
from app.schemas import AuditLog
from app.tests.pg_approved_instance import (
    ApprovedInstanceUnavailable, create_target_database, finalize_target,
    load_approved_instance, target_engine,
)


@pytest.fixture(params=['sqlite', 'postgres'])
def committed_receipts(request, tmp_path):
    target = None
    engine = None
    try:
        if request.param == 'sqlite':
            engine = create_engine(f'sqlite:///{tmp_path / "receipts.db"}')
        else:
            instance = load_approved_instance()
            target = create_target_database(instance)
            engine = target_engine(target)
        Base.metadata.create_all(engine)
        receipts = Table('rf004_evidence_receipts', MetaData(), Column('id', Integer, primary_key=True))
        receipts.create(engine)
        suite = ET.Element('testsuite')
        names = []
        for number in range(1, 18):
            name = f'test_committed_receipt_{number}'
            with Session(engine) as db:
                db.execute(receipts.insert().values(id=number))
                entry = log_action(db, None, 'verification_receipt', 'RF004Receipt', number,
                                   new_value={'receipt': number, 'amount': Decimal('7.50')})
                if request.param == 'postgres':
                    assert entry.id is None
                db.commit()
                assert entry.id is not None and entry.entry_hash
            names.append(name)
            ET.SubElement(suite, 'testcase', classname='app.tests.test_rf004_transaction_receipts', name=name)
        with Session(engine) as db:
            db.execute(receipts.insert().values(id=18))
            log_action(db, None, 'rolled_back_receipt', 'RF004Receipt', 18)
            db.rollback()
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(receipts)) == 17
            assert db.query(AuditLog).count() == 17
            assert verify_audit_hash_chain(db)['ok'] is True
        report = tmp_path / 'actual-receipts.xml'
        ET.ElementTree(suite).write(report)
        yield report, names
    finally:
        if target is not None:
            finalize_target(target, engine)
        elif engine is not None:
            engine.dispose()


def test_actual_receipts_preserve_distinct_primary_and_supplement_policies(committed_receipts, monkeypatch):
    report, names = committed_receipts
    owner = inspect.getmodule(primary.check_report)
    monkeypatch.setattr(owner, 'GROUPS', {'test_rf004_transaction_receipts': (17, ())})
    monkeypatch.setattr(owner, 'REQUIRED_CASES', {'test_rf004_transaction_receipts': names})
    assert primary.check_report(report) == {'test_rf004_transaction_receipts': 17}
    expected = [f'backend/app/tests/test_rf004_transaction_receipts.py::{name}' for name in names]
    assert supplement.check_report(report, expected)['case_count'] == 17
    root = ET.parse(report).getroot()
    ET.SubElement(root, 'testcase', classname='app.tests.test_rf004_transaction_receipts', name='test_verified_rollback')
    ET.ElementTree(root).write(report)
    assert primary.check_report(report) == {'test_rf004_transaction_receipts': 18}
    with pytest.raises(ValueError, match='expected exactly 17'):
        supplement.check_report(report, expected)
    root.remove(list(root)[-1])
    list(root)[1].set('name', names[0])
    ET.ElementTree(root).write(report)
    with pytest.raises(ValueError, match='duplicate'):
        primary.check_report(report)
    with pytest.raises(ValueError, match='duplicate'):
        supplement.check_report(report, expected)


def test_supplement_provenance_retains_existing_properties_and_appends(tmp_path):
    root = ET.Element('testsuites')
    for index in range(2):
        suite = ET.SubElement(root, 'testsuite', name=str(index))
        props = ET.SubElement(suite, 'properties')
        ET.SubElement(props, 'property', name='business_fixture', value='receipt')
    report = tmp_path / 'provenance.xml'
    ET.ElementTree(root).write(report)
    digest = hashlib.sha256(b'frozen manifest').hexdigest()
    supplement.add_provenance(report, 'first-source', digest)
    supplement.add_provenance(report, 'second-source', digest)
    for suite in ET.parse(report).getroot().iter('testsuite'):
        props = suite.find('properties')
        assert [(p.get('name'), p.get('value')) for p in props] == [
            ('business_fixture', 'receipt'), ('source_commit', 'first-source'),
            ('required_cases_manifest_sha256', digest), ('source_commit', 'second-source'),
            ('required_cases_manifest_sha256', digest),
        ]


def test_sqlite_cannot_be_authorized_as_postgres_and_native_instance_is_not_ci_job(monkeypatch):
    config = json.loads(os.environ['MILANA_TEST_PG_INSTANCE'])
    with monkeypatch.context() as patch:
        patch.setenv('MILANA_TEST_PG_INSTANCE', json.dumps({**config, 'admin_dsn': 'sqlite:///:memory:'}))
        with pytest.raises(ApprovedInstanceUnavailable):
            load_approved_instance()
        with pytest.raises(ValueError, match='approved PG17 target'):
            supplement.require_ci_instance()
    # The native mismatch must be explicit even when the surrounding job is CI.
    with monkeypatch.context() as patch:
        patch.setenv('MILANA_TEST_PG_INSTANCE', json.dumps({
            **config, 'port': 20400,
            'admin_dsn': 'postgresql+psycopg2://postgres@127.0.0.1:20400/postgres',
        }))
        with pytest.raises(ValueError, match='approved PG17 target'):
            supplement.require_ci_instance()


def test_supplement_manifest_is_frozen_to_the_two_existing_groups():
    nodes = supplement.expected_nodeids()
    assert len(nodes) == 17 and len(set(nodes)) == 17
    assert sum('test_purchase_request_reject_postgres_followup.py::' in n for n in nodes) == 7
    assert sum('test_fabric_scan_postgres_followup.py::' in n for n in nodes) == 10


@pytest.mark.parametrize('entrypoint', ['primary', 'supplement'])
@pytest.mark.parametrize('scenario', ['success', 'process_failure', 'missing_report', 'timeout'])
def test_existing_cli_exit_report_and_command_contracts(entrypoint, scenario, tmp_path, monkeypatch, capsys):
    import subprocess
    from types import SimpleNamespace

    module = primary if entrypoint == 'primary' else supplement
    report = tmp_path / 'cli.xml'
    calls = []
    if entrypoint == 'supplement':
        monkeypatch.setenv('MILANA_TEST_PG_INSTANCE', json.dumps({
            'admin_dsn': supplement.EXPECTED_ADMIN_DSN, 'host': '127.0.0.1', 'port': 55432,
            'target_prefix': supplement.EXPECTED_PREFIX, 'server_version': '17.7',
            'system_identifier': '123456', 'data_directory': '/owned/ci/data',
        }))
        monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: 'frozen-source\n')
    monkeypatch.setenv('PGPASSWORD', 'inherited-must-not-reach-primary')
    monkeypatch.setattr(module.sys, 'argv', [entrypoint, '--report', str(report)])

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert kwargs['check'] is False and kwargs['timeout'] == 1800
        assert kwargs['cwd'] == ROOT / 'backend'
        if entrypoint == 'primary':
            assert 'PGPASSWORD' not in kwargs['env']
            assert Path(kwargs['env']['PGPASSFILE']).read_bytes() == b''
        else:
            assert 'env' not in kwargs
            assert '--noconftest' in command and '--runxfail' in command
        if scenario == 'timeout':
            raise subprocess.TimeoutExpired(command, 1800)
        if scenario != 'missing_report':
            suite = ET.Element('testsuite')
            if entrypoint == 'primary':
                for name, nodes in primary.REQUIRED_CASES.items():
                    for node in nodes:
                        ET.SubElement(suite, 'testcase', classname='app.tests.' + name, name=node)
            else:
                for node in supplement.expected_nodeids():
                    path, name = node.split('::', 1)
                    ET.SubElement(suite, 'testcase', classname='app.tests.' + Path(path).stem, name=name)
            ET.ElementTree(suite).write(report)
        return SimpleNamespace(returncode=19 if scenario == 'process_failure' else 0)

    monkeypatch.setattr(module.subprocess, 'run', run)
    if scenario == 'success':
        assert module.main() == 0
        body = json.loads(capsys.readouterr().out)
        if entrypoint == 'primary':
            assert body['required_pg_gate'] == 'PASS'
            assert body['passed_case_counts'] == {name: len(nodes) for name, nodes in primary.REQUIRED_CASES.items()}
        else:
            assert body['required_pg_supplement'] == 'PASS' and body['case_count'] == 17
            assert body['source_commit'] == 'frozen-source'
            assert ET.parse(report).getroot().find('properties/property[@name="source_commit"]').get('value') == 'frozen-source'
    elif entrypoint == 'primary' and scenario == 'process_failure':
        assert module.main() == 19
    elif entrypoint == 'primary' and scenario == 'missing_report':
        with pytest.raises(FileNotFoundError):
            module.main()
    elif entrypoint == 'primary' and scenario == 'timeout':
        with pytest.raises(subprocess.TimeoutExpired):
            module.main()
    else:
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == 2
    assert len(calls) == 1
