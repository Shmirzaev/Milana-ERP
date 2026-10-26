"""Local tests for the storage/database recovery pairing manifest."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

import storage_recovery_manifest as recovery
from storage_recovery_manifest import FORMAT, create_manifest, main, verify_manifest


def _restore_output(rows=None):
    rows = rows or {}
    sections = []
    for table, columns in recovery.REFERENCE_COLUMNS.items():
        column = next(iter(columns))
        sections.extend((f"COPY public.{table} ({column}) FROM stdin;", *rows.get(table, []), r"\."))
    return "\n".join(sections) + "\n"


@pytest.fixture(autouse=True)
def fake_pg_restore(monkeypatch):
    def respond(command, **kwargs):
        assert command[0] == "pg_restore"
        assert "--data-only" in command and "--file=-" in command
        return subprocess.CompletedProcess(command, 0, _restore_output(), "")

    monkeypatch.setattr(recovery.subprocess, "run", respond)
    return lambda rows: monkeypatch.setattr(
        recovery.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, _restore_output(rows), ""),
    )


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_manifest_pairs_dump_and_entire_storage_tree(tmp_path: Path):
    dump = _write(tmp_path / "backup.dump", b"synthetic database dump")
    storage = tmp_path / "storage"
    _write(storage / "model_files" / "one.png", b"model image")
    _write(storage / "sales_order_files" / "drawing.pdf", b"drawing")
    manifest = create_manifest(dump, storage)

    assert manifest["format"] == FORMAT
    assert set(manifest["storage_files"]) == {
        "model_files/one.png",
        "sales_order_files/drawing.pdf",
    }
    manifest_path = _write(tmp_path / "pairing.json", json.dumps(manifest).encode())
    assert verify_manifest(manifest_path, dump, storage)["ok"] is True


def test_dump_references_are_checked_at_manifest_creation(tmp_path: Path, fake_pg_restore):
    dump = _write(tmp_path / "backup.dump", b"synthetic custom-format dump")
    storage = tmp_path / "storage"
    _write(storage / "model_files" / "one.png", b"model image")
    fake_pg_restore({
        "model_images": ["/storage/model-files/one.png"],
        "sales_orders": ['[{"file_url": "/storage/sales-order-files/missing.pdf"}]'],
    })
    with pytest.raises(ValueError, match="sales_order_files/missing.pdf"):
        create_manifest(dump, storage)


def test_verify_reports_missing_file_referenced_by_dump(tmp_path: Path, fake_pg_restore):
    dump = _write(tmp_path / "backup.dump", b"synthetic custom-format dump")
    storage = tmp_path / "storage"
    image = _write(storage / "model_files" / "one.png", b"model image")
    fake_pg_restore({"model_images": ["/storage/model-files/one.png"]})
    manifest_path = _write(tmp_path / "pairing.json", json.dumps(create_manifest(dump, storage)).encode())
    image.unlink()
    result = verify_manifest(manifest_path, dump, storage)
    assert result["ok"] is False
    assert result["missing_files"] == result["missing_referenced_files"] == ["model_files/one.png"]


def test_dump_references_include_hr_attendance_and_json(tmp_path: Path, fake_pg_restore):
    dump = _write(tmp_path / "backup.dump", b"synthetic custom-format dump")
    storage = tmp_path / "storage"
    for name in ("hr_documents/contract.pdf", "attendance_photos/face.webp", "sales_order_files/art.pdf"):
        _write(storage / name, b"file")
    fake_pg_restore({
        "hr_employee_documents": ["contract.pdf"],
        "attendance_people": ["face.webp"],
        "production_orders": ['[{"file_url": "/storage/sales-order-files/art.pdf"}]'],
        "model_images": ["https://external.example/image.png"],
    })
    manifest = create_manifest(dump, storage)
    assert manifest["database_references"] == [
        "attendance_photos/face.webp", "hr_documents/contract.pdf", "sales_order_files/art.pdf",
    ]


def test_company_logo_and_cutting_passport_references(tmp_path: Path, fake_pg_restore):
    dump = _write(tmp_path / "backup.dump", b"synthetic custom-format dump")
    storage = tmp_path / "storage"
    _write(storage / "model_files" / "logo.webp", b"logo")
    fake_pg_restore({
        "system_settings": ['{"logo_url": "/storage/model-files/logo.webp"}'],
        "cutting_passports": ["/storage/model-files/logo.webp"],
    })
    assert create_manifest(dump, storage)["database_references"] == ["model_files/logo.webp"]


def test_incomplete_dump_reference_coverage_fails_closed(tmp_path: Path, monkeypatch):
    dump = _write(tmp_path / "backup.dump", b"synthetic custom-format dump")
    storage = tmp_path / "storage"
    storage.mkdir()
    output = "COPY public.model_images (file_url) FROM stdin;\n\\.\n"
    monkeypatch.setattr(recovery.subprocess, "run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 0, output, ""))
    with pytest.raises(ValueError, match="lacks upload table data"):
        create_manifest(dump, storage)


def test_dump_changed_while_reading_is_rejected(tmp_path: Path, monkeypatch):
    dump = _write(tmp_path / "backup.dump", b"before")
    storage = tmp_path / "storage"
    storage.mkdir()

    def change_dump(command, **kwargs):
        dump.write_bytes(b"after")
        return subprocess.CompletedProcess(command, 0, _restore_output(), "")

    monkeypatch.setattr(recovery.subprocess, "run", change_dump)
    with pytest.raises(ValueError, match="changed during verification"):
        create_manifest(dump, storage)


def test_mismatched_snapshot_pair_identity_fails(tmp_path: Path):
    first_dump = _write(tmp_path / "first.dump", b"first custom-format dump")
    second_dump = _write(tmp_path / "second.dump", b"second custom-format dump")
    first_storage = tmp_path / "first-storage"
    second_storage = tmp_path / "second-storage"
    _write(first_storage / "model_files" / "one.png", b"first image")
    _write(second_storage / "model_files" / "one.png", b"second image")
    manifest_path = _write(tmp_path / "pairing.json", json.dumps(create_manifest(first_dump, first_storage)).encode())
    result = verify_manifest(manifest_path, second_dump, second_storage)
    assert result["ok"] is False
    assert result["database_dump_matches"] is False
    assert result["changed_files"] == ["model_files/one.png"]


@pytest.mark.parametrize("change", ["missing", "extra", "changed", "dump"])
def test_verify_reports_artifact_drift(tmp_path: Path, change: str):
    dump = _write(tmp_path / "backup.dump", b"synthetic database dump")
    storage = tmp_path / "storage"
    _write(storage / "model_files" / "one.png", b"original")
    manifest_path = _write(tmp_path / "pairing.json", json.dumps(create_manifest(dump, storage)).encode())

    if change == "missing":
        (storage / "model_files" / "one.png").unlink()
    elif change == "extra":
        _write(storage / "hr_documents" / "new.pdf", b"new file")
    elif change == "changed":
        _write(storage / "model_files" / "one.png", b"replacement")
    else:
        dump.write_bytes(b"different dump")

    result = verify_manifest(manifest_path, dump, storage)
    assert result["ok"] is False
    if change == "missing":
        assert result["missing_files"] == ["model_files/one.png"]
    elif change == "extra":
        assert result["extra_files"] == ["hr_documents/new.pdf"]
    elif change == "changed":
        assert result["changed_files"] == ["model_files/one.png"]
    else:
        assert result["database_dump_matches"] is False


def test_inventory_rejects_symlink_without_following_it(tmp_path: Path):
    dump = _write(tmp_path / "backup.dump", b"dump")
    storage = tmp_path / "storage"
    storage.mkdir()
    external = _write(tmp_path / "outside.txt", b"outside")
    try:
        (storage / "link.txt").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this filesystem")

    with pytest.raises(ValueError, match="symbolic links"):
        create_manifest(dump, storage)


@pytest.mark.parametrize("symlink_target", ["storage-root", "database-dump"])
def test_manifest_rejects_symlinked_artifact_paths(tmp_path: Path, symlink_target: str):
    dump = _write(tmp_path / "backup.dump", b"dump")
    storage = tmp_path / "storage"
    storage.mkdir()

    if symlink_target == "storage-root":
        linked_path = tmp_path / "storage-alias"
        try:
            linked_path.symlink_to(storage, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this filesystem")
        storage_argument = linked_path
        dump_argument = dump
    else:
        linked_path = tmp_path / "dump-alias.dump"
        try:
            linked_path.symlink_to(dump)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this filesystem")
        storage_argument = storage
        dump_argument = linked_path

    with pytest.raises(ValueError, match="symbolic link"):
        create_manifest(dump_argument, storage_argument)


def test_create_does_not_overwrite_existing_manifest(tmp_path: Path, monkeypatch, capsys):
    dump = _write(tmp_path / "backup.dump", b"dump")
    storage = tmp_path / "storage"
    storage.mkdir()
    output = _write(tmp_path / "pairing.json", b"keep existing")
    monkeypatch.setattr(
        "sys.argv",
        [
            "storage_recovery_manifest.py",
            "create",
            "--database-dump",
            str(dump),
            "--storage-root",
            str(storage),
            "--output",
            str(output),
        ],
    )

    assert main() == 2
    assert output.read_bytes() == b"keep existing"
    assert "already exists" in capsys.readouterr().err


def test_create_writes_private_manifest_without_changing_artifacts(tmp_path: Path, monkeypatch):
    dump = _write(tmp_path / "backup.dump", b"dump")
    storage = tmp_path / "storage"
    image = _write(storage / "model_files" / "one.png", b"image")
    output = tmp_path / "pairing.json"
    monkeypatch.setattr("sys.argv", [
        "storage_recovery_manifest.py", "create", "--database-dump", str(dump),
        "--storage-root", str(storage), "--output", str(output),
    ])
    assert main() == 0
    assert dump.read_bytes() == b"dump" and image.read_bytes() == b"image"
    if os.name == "posix":
        assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_manifest_path_traversal_is_rejected(tmp_path: Path):
    dump = _write(tmp_path / "backup.dump", b"dump")
    storage = tmp_path / "storage"
    storage.mkdir()
    manifest_path = _write(
        tmp_path / "pairing.json",
        json.dumps(
            {
                "format": FORMAT,
                "database_dump": {"size_bytes": 4, "sha256": "a" * 64},
                "storage_files": {"../outside": {"size_bytes": 1, "sha256": "b" * 64}},
                "database_references": [],
            }
        ).encode(),
    )

    with pytest.raises(ValueError, match="invalid storage entry"):
        verify_manifest(manifest_path, dump, storage)
