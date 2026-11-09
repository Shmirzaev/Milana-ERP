import hashlib
import pytest
from stage_live_worker import FILES, stage


def test_separate_package_has_only_reviewed_source_and_never_activates(tmp_path):
    destination=tmp_path/"new-writer"
    manifest=stage(destination)
    assert set(p.name for p in destination.iterdir()) == {*FILES, "WRITER_MANIFEST.json"}
    assert manifest["activated"] is False
    assert "read_only_connector.py" not in FILES and "config.json" not in FILES
    for name, value in manifest["files"].items():
        assert hashlib.sha256((destination/name).read_bytes()).hexdigest() == value["sha256"]


def test_existing_installation_is_refused_without_changes(tmp_path):
    sentinel=tmp_path/"config.json";sentinel.write_text("private original",encoding="utf-8")
    with pytest.raises(FileExistsError):stage(tmp_path)
    assert list(tmp_path.iterdir()) == [sentinel] and sentinel.read_text() == "private original"
