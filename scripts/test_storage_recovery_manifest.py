"""Local tests for the storage/database recovery pairing manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from storage_recovery_manifest import FORMAT, create_manifest, main, verify_manifest


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
            }
        ).encode(),
    )

    with pytest.raises(ValueError, match="invalid storage entry"):
        verify_manifest(manifest_path, dump, storage)
