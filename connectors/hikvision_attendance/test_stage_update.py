import hashlib
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from stage_update import UPDATE_FILES, stage_update


def source_tree(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name in UPDATE_FILES:
        (source / name).write_bytes(("candidate " + name).encode())
    # These must never be copied, read into the manifest or overwritten.
    for name in ("config.json", "secrets.dpapi.json", "state.json", "state.turnstile-73.json", "run_scheduled_hidden.vbs"):
        (source / name).write_text("private preserved installation data", encoding="utf-8")
    return source


def test_staged_update_contains_only_verified_source_files(tmp_path):
    source = source_tree(tmp_path)
    destination = tmp_path / "candidate"
    manifest = stage_update(destination, source)
    assert set(p.name for p in destination.iterdir()) == set(UPDATE_FILES) | {"UPDATE_MANIFEST.json"}
    assert json.loads((destination / "UPDATE_MANIFEST.json").read_text()) == manifest
    for name, evidence in manifest["files"].items():
        content = (source / name).read_bytes()
        assert (destination / name).read_bytes() == content
        assert evidence == {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    assert b"private preserved" not in (destination / "UPDATE_MANIFEST.json").read_bytes()


@pytest.mark.parametrize("has_config", [False, True])
def test_existing_installation_is_never_overwritten(tmp_path, has_config):
    source = source_tree(tmp_path)
    installed = tmp_path / "installed"
    installed.mkdir()
    if has_config:
        (installed / "config.json").write_bytes(b"existing config")
    before = {p.name: p.read_bytes() for p in installed.iterdir()}
    with pytest.raises(FileExistsError):
        stage_update(installed, source)
    assert {p.name: p.read_bytes() for p in installed.iterdir()} == before


def test_missing_candidate_fails_before_creating_output(tmp_path):
    source = source_tree(tmp_path)
    (source / UPDATE_FILES[-1]).unlink()
    with pytest.raises(ValueError, match="regular file"):
        stage_update(tmp_path / "candidate", source)
    assert not (tmp_path / "candidate").exists()


def test_windows_timezone_fallback_is_available():
    # Windows normally lacks the system IANA database. Exercise the tzdata
    # package path instead of accidentally relying on the host's zone files.
    import zoneinfo
    original_path = zoneinfo.TZPATH
    zoneinfo.reset_tzpath(())
    try:
        assert ZoneInfo.no_cache("Asia/Tashkent").utcoffset(datetime(2026, 11, 9)) == timedelta(hours=5)
    finally:
        zoneinfo.reset_tzpath(original_path)
