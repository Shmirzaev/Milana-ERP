import hashlib
import json
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw
from extract_fabric_workbooks import SOURCE, FILES, OUT

NS = {'d':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}

def main():
    result=[]
    for file_no, filename in enumerate(FILES):
        z=zipfile.ZipFile(SOURCE/filename)
        for name in z.namelist():
            if not (name.startswith('xl/drawings/drawing') and name.endswith('.xml')): continue
            relname=posixpath.dirname(name)+'/_rels/'+posixpath.basename(name)+'.rels'
            rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read(relname))}
            tiles=[]
            for anchor in ET.fromstring(z.read(name)):
                row=anchor.find('d:from/d:row',NS); blip=anchor.find('.//a:blip',NS)
                if row is None or blip is None: continue
                target=rels[blip.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed']]
                target=target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(name),target))
                raw=z.read(target); row_no=int(row.text)+1
                result.append({'file':filename,'drawing':name,'row':row_no,'media':target,'sha256':hashlib.sha256(raw).hexdigest()})
                if file_no==0 and name=='xl/drawings/drawing2.xml':
                    dest=OUT/'sheet5-pictures';dest.mkdir(exist_ok=True)
                    (dest/f'row-{row_no}{Path(target).suffix}').write_bytes(raw)
                    im=Image.open(BytesIO(raw)).convert('RGB');im.thumbnail((280,220))
                    tile=Image.new('RGB',(300,250),'white');tile.paste(im,((300-im.width)//2,25));ImageDraw.Draw(tile).text((10,5),f'Row {row_no}',fill='black');tiles.append(tile)
            if tiles:
                contact=Image.new('RGB',(1200,250*((len(tiles)+3)//4)),'#dddddd')
                for i,tile in enumerate(tiles): contact.paste(tile,((i%4)*300,(i//4)*250))
                contact.save(OUT/'sheet5-pictures.png')
    (OUT/'source-pictures.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Extracted image references:',len(result))

if __name__=='__main__':main()
