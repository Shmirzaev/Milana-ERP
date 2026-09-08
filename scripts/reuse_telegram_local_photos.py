"""Reuse source-indexed local Telegram originals only when unambiguous."""
import hashlib
import json
import re
import shutil
from pathlib import Path
from PIL import Image


root = Path(__file__).resolve().parents[1]
evidence = root/'evidence'
plan = json.loads((evidence/'telegram-local-normalized-source-plan.json').read_text('utf-8'))
log_path = evidence/'telegram-downloads.json'
log = json.loads(log_path.read_text('utf-8'))
done = {r['model_no'] for r in log}
reused, held = [], []
for row in plan['selected']:
    if row['model_no'] in done:
        continue
    choices = []
    source = row['source']
    for candidate in source['local_candidates']:
        path = Path(candidate['path'])
        assert path.resolve().is_relative_to(Path('C:/Users/User/Downloads').resolve())
        data = path.read_bytes()
        if len(data) != candidate['bytes']:
            continue
        size = re.search(r'\n([\d.]+)(KB|MB|GB)', source['text'])
        scale = {'KB':1024, 'MB':1024**2, 'GB':1024**3}[size[2]]
        if abs(len(data)/scale-float(size[1])) > .11:
            continue
        with Image.open(path) as image:
            image.verify()
        choices.append((hashlib.sha256(data).hexdigest(), path, len(data)))
    if not choices or len({c[0] for c in choices}) != 1:
        held.append({'model_no':row['model_no'], 'reason':'conflicting or missing local originals'})
        continue
    checksum, path, byte_size = choices[0]
    relative = 'evidence/telegram-originals/' + source['id'] + path.suffix.lower()
    shutil.copyfile(path, root/relative)
    clean_source = {k:v for k,v in source.items() if k != 'local_candidates'}
    record = {'model_no':row['model_no'], 'source':clean_source, 'downloaded_name':path.name,
              'local_path':relative, 'bytes':byte_size, 'local_original_path':str(path),
              'local_original_sha256':checksum, 'acquisition':'existing Telegram download; indexed filename and size verified'}
    log.append(record)
    reused.append(row['model_no'])
temporary = log_path.with_suffix('.tmp')
temporary.write_text(json.dumps(log,ensure_ascii=False,indent=2),'utf-8')
temporary.replace(log_path)
(evidence/'telegram-local-reuse-result.json').write_text(json.dumps({'reused':reused,'held':held},indent=2),'utf-8')
print(json.dumps({'reused':len(reused),'held':len(held),'total_originals':len(log)}))
