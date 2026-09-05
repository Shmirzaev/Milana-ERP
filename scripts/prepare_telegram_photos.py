"""Validate downloaded originals; optionally store lossless PNG derivatives."""
import argparse
import hashlib
import io
import json
import re
import time
from pathlib import Path
from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def prepare(root, row):
    source = (root / row['local_path']).resolve()
    assert source.is_relative_to(root.resolve() / 'evidence' / 'telegram-originals')
    original = source.read_bytes()
    assert len(original) == row['bytes']
    displayed = re.search(r'\n([\d.]+)(KB|MB|GB)', row['source']['text'])
    assert displayed, 'Missing source file size'
    scale = {'KB':1024, 'MB':1024**2, 'GB':1024**3}[displayed[2]]
    assert abs(len(original)/scale-float(displayed[1])) <= .11, 'Downloaded preview is not the indexed original'
    with Image.open(io.BytesIO(original)) as image:
        image.load()
        assert image.width * image.height <= 50_000_000
        mode = 'RGBA' if 'A' in image.getbands() else 'RGB'
        pixels = image.convert(mode)
        pixel_sha = sha(pixels.tobytes())
        data, extension = original, source.suffix.lower()
        if image.format == 'PNG':
            buffer = io.BytesIO()
            options = {key: image.info[key] for key in ('icc_profile', 'exif') if key in image.info}
            pixels.save(buffer, format='WEBP', lossless=True, exact=True, method=4, **options)
            candidate = buffer.getvalue()
            with Image.open(io.BytesIO(candidate)) as check:
                assert check.size == image.size and sha(check.convert(mode).tobytes()) == pixel_sha
            if len(candidate) < len(original):
                data, extension = candidate, '.webp'
        name = f"telegram_model_20260905_{row['source']['id'].split('-')[-1]}_{sha(data)[:16]}{extension}"
        target = root / 'evidence' / 'telegram-prepared' / name
        target.parent.mkdir(exist_ok=True)
        if target.exists():
            assert target.read_bytes() == data
        else:
            target.write_bytes(data)
        return {**row, 'stored_name': name, 'stored_bytes': len(data), 'sha256': sha(data),
                'original_sha256': sha(original), 'pixel_sha256': pixel_sha,
                'width': image.width, 'height': image.height,
                'content_type': 'image/webp' if extension == '.webp' else Image.MIME[image.format]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected', type=int, default=0)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'evidence' / 'telegram-prepared.json'
    prepared = json.loads(output.read_text('utf-8')) if output.exists() else []
    while True:
        downloads = json.loads((root/'evidence/telegram-downloads.json').read_text('utf-8'))
        for row in downloads:
            if any(p['model_no'] == row['model_no'] for p in prepared):
                continue
            prepared.append(prepare(root, row))
            temporary = output.with_suffix('.tmp')
            temporary.write_text(json.dumps(prepared, ensure_ascii=False, indent=2), 'utf-8')
            temporary.replace(output)
            print(json.dumps({'prepared': len(prepared), 'model': row['model_no']}), flush=True)
        if not args.expected or len(prepared) >= args.expected:
            break
        time.sleep(2)
