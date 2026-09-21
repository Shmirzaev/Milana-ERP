from pathlib import Path
import xml.etree.ElementTree as ET
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import toColor as HexColor
import pymupdf
from PIL import Image,ImageDraw

root=Path(__file__).resolve().parents[3]
src=root/'docs/workflow/figma/svg';out=root/'tmp/svg-qa';out.mkdir(parents=True,exist_ok=True)
pdfmetrics.registerFont(TTFont('ERP','C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('ERP-Bold','C:/Windows/Fonts/arialbd.ttf'))
issues=[];thumbs=[]
for svg in sorted(src.glob('*.svg')):
    tree=ET.parse(svg).getroot();w=float(tree.attrib['width']);h=float(tree.attrib['height'])
    pdf=out/(svg.stem+'.pdf');c=canvas.Canvas(str(pdf),pagesize=(w,h))
    for n in tree.iter():
        tag=n.tag.rsplit('}',1)[-1];a=n.attrib
        if tag=='rect':
            c.setFillColor(HexColor(a.get('fill','#ffffff')));c.setStrokeColor(HexColor(a.get('stroke','#ffffff')))
            x=float(a.get('x',0));y=float(a.get('y',0));rw=float(a['width']);rh=float(a['height']);c.rect(x,h-y-rh,rw,rh,fill=1,stroke=int('stroke'in a))
        if tag=='text':
            x=float(a['x']);y=float(a['y']);size=float(a['font-size']);font='ERP-Bold' if a.get('font-weight')=='600' else 'ERP';txt=n.text or ''
            width=pdfmetrics.stringWidth(txt,font,size)
            if x+width>w-25:issues.append({'file':svg.name,'text':txt,'right':x+width})
            c.setFillColor(HexColor(a.get('fill','#14110b')));c.setFont(font,size);c.drawString(x,h-y,txt)
    c.save();doc=pymupdf.open(pdf);page=doc[0];scale=min(.55,1500/h);pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale));png=out/(svg.stem+'.png');pix.save(png)
    im=Image.open(png).convert('RGB');im.thumbnail((265,690));tile=Image.new('RGB',(285,730),'#eeeeee');tile.paste(im,((285-im.width)//2,26));ImageDraw.Draw(tile).text((8,7),svg.stem,fill='black');thumbs.append(tile)
for start in range(0,len(thumbs),8):
    subset=thumbs[start:start+8];sheet=Image.new('RGB',(1140,1460),'white')
    for j,im in enumerate(subset):sheet.paste(im,((j%4)*285,(j//4)*730))
    sheet.save(out/f'contact-{start//8+1}.png')
(out/'qa.json').write_text(json.dumps({'svgCount':len(thumbs),'overflow':issues},indent=2),encoding='utf8')
print(json.dumps({'svgCount':len(thumbs),'overflow':issues}))
