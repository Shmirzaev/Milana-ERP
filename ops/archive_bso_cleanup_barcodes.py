"""Archive exact generated barcode paths before cleanup; remove after commit."""
import hashlib
import json
import re
import shutil
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_media(plan, backup, committed=None):
    stamp = Path(backup['path']).stem.removeprefix('milana_erp_pre_bso_cleanup_')
    assert re.fullmatch(r'\d{8}_\d{6}', stamp)
    root = Path('/barcodes').resolve(strict=True)
    archive = Path('/backup') / ('bso_cleanup_'+stamp)
    archive.mkdir(mode=0o700, exist_ok=True)
    assert archive.resolve().parent == Path('/backup').resolve()
    names = plan['barcode_filenames']
    assert all(re.fullmatch(r'(bundle|package)_(qr|bc)_[A-Za-z0-9_-]+\.png', n) for n in names)
    manifest_path = archive/'media-manifest.json'
    if committed is None:
        assert not manifest_path.exists(), 'Archive already prepared'
        manifest = []
        for name in names:
            source = root/name
            assert not source.is_symlink() and source.resolve().parent == root
            if not source.exists():
                continue
            assert source.is_file()
            target = archive/name
            assert not target.exists()
            shutil.copy2(source, target)
            target.chmod(0o600)
            checksum = digest(source)
            assert checksum == digest(target)
            manifest.append(dict(name=name, sha256=checksum, bytes=source.stat().st_size))
        manifest_path.write_text(json.dumps(manifest, indent=2))
        manifest_path.chmod(0o600)
        return dict(archived_files=len(manifest), bytes=sum(r['bytes'] for r in manifest),
                    manifest_sha256=digest(manifest_path),
                    archive='/opt/milana-erp/shared/backups/'+archive.name)
    assert committed['deleted'] == plan['counts'] and committed['audit_id']
    assert committed['backup'] == backup
    manifest = json.loads(manifest_path.read_text())
    for row in manifest:
        assert row['name'] in names
        source = root/row['name']
        assert source.resolve().parent == root and not source.is_symlink()
        assert digest(source) == row['sha256'] == digest(archive/row['name'])
    for row in manifest:
        (root/row['name']).unlink()
    assert all(not (root/row['name']).exists() for row in manifest)
    return dict(removed_files=len(manifest), archive='/opt/milana-erp/shared/backups/'+archive.name)
