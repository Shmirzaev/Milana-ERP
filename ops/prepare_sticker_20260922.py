"""Extract supplied PDF labels and independently decode their QR symbols."""
import hashlib
import json
import re
import zipfile
from pathlib import Path
from collections import Counter
import pymupdf as fitz
import zxingcpp
from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / 'outputs' / 'sticker-20260922'
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / 'pdfs').mkdir(exist_ok=True)
source = Path(r'C:\Users\User\Downloads\sticker.zip')
rows, problems, duplicates, pages = [], [], [], 0
seen = {}
with zipfile.ZipFile(source) as archive:
    for name in archive.namelist():
        if not name.lower().endswith('.pdf'):
            continue
        raw = archive.read(name)
        name = Path(name).name
        (ROOT / 'pdfs' / name).write_bytes(raw)
        doc = fitz.open(stream=raw, filetype='pdf')
        for pno, page in enumerate(doc, 1):
            pages += 1
            wide = 'Milana - Made in Uzbekistan' in page.get_text()
            for quadrant, (x,y) in enumerate([(0,0),(0,1)] if wide else [(0,0),(0,1),(1,0),(1,1)],1):
                rect = fitz.Rect(x*page.rect.width/2,y*page.rect.height/2,page.rect.width if wide else (x+1)*page.rect.width/2,(y+1)*page.rect.height/2)
                text = page.get_text(clip=rect)
                if 'Model number' not in text:
                    if text.strip(): problems.append({'file':name,'page':pno,'quadrant':quadrant,'reason':'unrecognized label','text':text})
                    continue
                words = page.get_text('words',clip=rect)
                def field(label):
                    tokens = label.split()
                    anchors = [w for w in words if w[4]==tokens[-1] and w[0]<rect.x0+80]
                    assert len(anchors)==1, (label,anchors)
                    a=anchors[0]
                    return ' '.join(w[4] for w in sorted(words,key=lambda w:w[0]) if w[0]>a[2]+1 and abs((w[1]+w[3]-a[1]-a[3])/2)<4)
                try:
                    qrtext = re.findall(r'uzerp_ii_\d+_\d+|(?m:^\d{7}$)',text)
                    assert len(qrtext)==1, qrtext
                    qr=qrtext[0]
                    decoded=[]
                    for dpi in (200,400):
                        pix=page.get_pixmap(clip=rect,dpi=dpi)
                        decoded=[b.text for b in zxingcpp.read_barcodes(Image.frombytes('RGB',[pix.width,pix.height],pix.samples))]
                        if qr in decoded: break
                    assert decoded==[qr], ('QR mismatch',decoded,qr)
                    weight=field('Weight').replace(',','.')
                    row=dict(qr_code=qr,model_number=field('Model number'),article=field('Articul'),quantity=int(field('Quantity')),weight_kg=weight or None,sizes=field('Size chast').split(),source_file=name,source_page=pno,source_sequence=quadrant,file_sha256=hashlib.sha256(raw).hexdigest())
                    if wide:
                        model_variant=re.fullmatch(r'(.+?)\s+(V-\d+)',row['model_number'])
                        assert model_variant, row
                        row['model_number'],row['article']=model_variant.groups()
                        row['model_number']=row['model_number'].replace(' ','')
                    else:
                        row.update(color=field('Color'),product=field('Product'),fabric=field('Fabric'),client=field('Client'))
                    assert row['model_number'] and row['article'] and row['sizes'] and row['quantity']>0
                    if qr in seen:
                        assert all(row[k]==seen[qr][k] for k in ('model_number','article','quantity','weight_kg','sizes')), ('conflicting duplicate',row,seen[qr])
                        duplicates.append(row)
                    else: rows.append(row); seen[qr]=row
                except Exception as e:
                    problems.append({'file':name,'page':pno,'quadrant':quadrant,'reason':str(e),'text':text})
                    page.get_pixmap(clip=rect,dpi=160).save(ROOT / f'problem-{len(problems)}.png')
        print(name, 'done',flush=True)
result=dict(source_zip='sticker.zip',source_zip_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),rows=rows,duplicates=duplicates,problems=problems,pages=pages)
(ROOT/'extracted.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(rows=len(rows),quantity=sum(r['quantity'] for r in rows),pages=pages,duplicates=len(duplicates),problems=len(problems),null_weights=sum(r['weight_kg'] is None for r in rows))))
