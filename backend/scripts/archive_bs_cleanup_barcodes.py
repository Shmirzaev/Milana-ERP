"""Archive exact reviewed generated barcodes; remove only after DB cleanup commits."""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan',required=True)
    parser.add_argument('--archive',required=True)
    parser.add_argument('--remove',action='store_true')
    parser.add_argument('--committed-result')
    args = parser.parse_args()
    root = Path('/app/storage/barcodes').resolve(strict=True)
    archive = Path(args.archive)
    assert re.fullmatch(r'/opt/milana-erp/shared/backups/bs_before_0032_\d{8}_\d{6}',str(archive))
    plan = json.loads(Path(args.plan).read_text())
    names = plan['barcode_filenames']
    assert all(re.fullmatch(r'(bundle|package)_(qr|bc)_[A-Za-z0-9_-]+\.png',name) for name in names)
    archive.mkdir(mode=0o700,exist_ok=True)
    assert archive.resolve().parent == Path('/opt/milana-erp/shared/backups').resolve()
    manifest_path = archive/'media-manifest.json'
    if not args.remove:
        assert not manifest_path.exists(), 'Archive already prepared'
        manifest = []
        for name in names:
            source = root/name
            assert source.resolve().parent == root and not source.is_symlink()
            if not source.exists():
                continue
            assert source.is_file()
            target = archive/name
            assert not target.exists()
            shutil.copy2(source,target)
            target.chmod(0o600)
            checksum = digest(source)
            assert checksum == digest(target)
            manifest.append({'name':name,'sha256':checksum,'bytes':source.stat().st_size})
        manifest_path.write_text(json.dumps(manifest,indent=2))
        manifest_path.chmod(0o600)
        print(json.dumps({'archived_files':len(manifest),'bytes':sum(r['bytes'] for r in manifest),'manifest_sha256':digest(manifest_path),'archive':str(archive)}))
        return
    result = json.loads(Path(args.committed_result).read_text())
    assert result['deleted']==plan['counts'] and result['audit_id']
    manifest = json.loads(manifest_path.read_text())
    # Verify every path and backup before removing any file.
    for row in manifest:
        assert row['name'] in names
        source = root/row['name']
        assert source.resolve().parent == root and not source.is_symlink()
        assert digest(source)==row['sha256']==digest(archive/row['name'])
    for row in manifest:
        (root/row['name']).unlink()
    assert all(not (root/row['name']).exists() for row in manifest)
    print(json.dumps({'removed_active_files':len(manifest),'archive':str(archive)}))


if __name__=='__main__':
    main()
