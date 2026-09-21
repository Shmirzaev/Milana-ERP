from pathlib import Path
import re
import html
import json
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable, KeepTogether, CondPageBreak
import pymupdf
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / 'docs/workflow'
OUT = ROOT / 'output/pdf'
QA = ROOT / 'tmp/pdfs'
OUT.mkdir(parents=True, exist_ok=True)
QA.mkdir(parents=True, exist_ok=True)
pdfmetrics.registerFont(TTFont('ERP', 'C:/Windows/Fonts/arial.ttf'))
pdfmetrics.registerFont(TTFont('ERP-Bold', 'C:/Windows/Fonts/arialbd.ttf'))
pdfmetrics.registerFontFamily('ERP', normal='ERP', bold='ERP-Bold', italic='ERP', boldItalic='ERP-Bold')
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyERP',fontName='ERP',fontSize=10.3,leading=14.5,spaceAfter=7,splitLongWords=True))
styles.add(ParagraphStyle(name='TableERP',fontName='ERP',fontSize=8.8,leading=12,spaceAfter=0,splitLongWords=True))
styles.add(ParagraphStyle(name='HeaderERP',fontName='ERP-Bold',fontSize=8.8,leading=12,textColor=colors.white))
for name,size,leading in [('Title',26,32),('Heading1',19,24),('Heading2',15,20),('Heading3',12,17)]:
    styles[name].fontName='ERP-Bold';styles[name].fontSize=size;styles[name].leading=leading;styles[name].textColor=colors.HexColor('#14110b');styles[name].spaceBefore=15;styles[name].spaceAfter=9;styles[name].keepWithNext=(name == 'Heading3')

def inline(s):
    s=s.replace('•',' | ').replace('—','-').replace('–','-')
    s=re.sub(r'\[([^]]+)\]\([^)]+\)',r'\1',s)
    s=html.escape(s)
    s=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',s)
    s=s.replace('`','')
    return s

class Lifecycle(Flowable):
    def __init__(self): super().__init__();self.width=504;self.height=252
    def draw(self):
        c=self.canv
        rows=[['Demand','Planning','Cutting','Bundles'],['Printing if needed','Sewing','Packaging','Warehouse receipt'],['Available stock','Reserve and pick','Scan and dispatch','Delivery']]
        for ri,row in enumerate(rows):
            for ci,label in enumerate(row):
                column=3-ci if ri==1 else ci
                x=column*128;y=194-ri*70
                c.setFillColor(colors.HexColor('#f8f7f3'));c.setStrokeColor(colors.HexColor('#ded9ca'));c.rect(x,y,116,48,fill=1)
                c.setFillColor(colors.HexColor('#14110b'));c.setFont('ERP',9)
                words=label.split();line='';lines=[]
                for word in words:
                    if pdfmetrics.stringWidth(line+' '+word,'ERP',9)>101:lines.append(line);line=word
                    else:line+=((' ' if line else '')+word)
                lines.append(line)
                for li,t in enumerate(lines):c.drawCentredString(x+58,y+29-li*12,t)
                if ri!=1 and ci<3:c.drawString(x+118,y+20,'→')
                if ri==1 and ci>0:c.drawString(x+118,y+20,'←')
        c.drawString(438,180,'↓');c.drawString(54,110,'↓')
        c.setFont('ERP',9);c.drawString(0,0,'Business sequence only. Defects remain loss; singles require size evidence and receipt.')

def table(rows):
    cols=len(rows[0]);width=504
    if cols==2:widths=[155,349]
    elif cols==3:widths=[135,175,194]
    elif cols==4:widths=[90,142,160,112]
    elif cols==5:widths=[70,125,110,110,89]
    else:widths=[width/cols]*cols
    cells=[[Paragraph(inline(c),styles['HeaderERP' if i==0 else 'TableERP']) for c in row] for i,row in enumerate(rows)]
    t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#3b3528')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#ded9ca')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#faf9f6')])]))
    return t

def markdown(file):
    lines=file.read_text(encoding='utf8').splitlines();result=[];i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('```'):
            i+=1
            while i<len(lines) and not lines[i].startswith('```'):i+=1
            preceding=result.pop() if result and isinstance(result[-1],Paragraph) else Spacer(1,1)
            result.append(KeepTogether([preceding,Spacer(1,6),Lifecycle(),Spacer(1,12)]));i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                s=lines[i].strip()
                if not re.match(r'^\|[\s|:\-]+\|$',s):
                    # Pipes inside inline code are literal alternatives.
                    s=re.sub(r'`[^`]*`',lambda m:m.group(0).replace('|',' / '),s)
                    rows.append([c.strip() for c in s.strip('|').split('|')])
                i+=1
            n=max(map(len,rows));rows=[r+['']*(n-len(r)) for r in rows]
            result.extend([table(rows),Spacer(1,12)]);continue
        if line.startswith('#'):
            level=len(line)-len(line.lstrip('#'));heading=line[level:].strip()
            if level==1:style='Heading1'
            elif level==2:style='Heading2'
            else:style='Heading3'
            result.append(CondPageBreak(110))
            result.append(Paragraph(inline(heading),styles[style]));i+=1;continue
        if re.match(r'^(- |\d+\. )',line):
            result.append(Paragraph(inline(line),styles['BodyERP']));i+=1;continue
        para=[line];i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r'^(#|\||```|- |\d+\. )',lines[i].strip()):para.append(lines[i].strip());i+=1
        result.append(Paragraph(inline(' '.join(para)),styles['BodyERP']))
    return result

def footer(c,doc):
    c.saveState();c.setFont('ERP',8);c.setFillColor(colors.HexColor('#56503f'))
    c.drawString(54,30,'Milana ERP | Business workflow and navigation | 21 September 2026')
    c.drawRightString(558,30,str(doc.page));c.restoreState()

story=[Spacer(1,52),Paragraph('Milana ERP',styles['Title']),Paragraph('Business requirements and workflow',styles['Heading1']),Paragraph('Page and button navigation guide',styles['Heading2']),Spacer(1,22),Paragraph('A functional manual for department managers, operators, product owners and designers. Covers demand, materials, production, packaging, warehouse, shipment and supporting business modules.',styles['BodyERP']),Spacer(1,20),Paragraph('Source release 20260920_030043<br/>Documentation date 21 September 2026<br/>102 route templates | 96 sidebar entries | 948 control definitions',styles['BodyERP']),Spacer(1,22),Paragraph('This manual describes source-verified behavior and explicit business requirements. It does not claim a new full security audit or live execution of every transaction. The editable route and control registers accompany this PDF.',styles['BodyERP']),PageBreak()]
story+=markdown(SRC/'BUSINESS_REQUIREMENTS.md')
story.append(Spacer(1,24));story+=markdown(SRC/'NAVIGATION_GUIDE.md')
pdf=OUT/'Milana-ERP-Business-Workflow-and-Navigation.pdf'
SimpleDocTemplate(str(pdf),pagesize=(612,792),leftMargin=54,rightMargin=54,topMargin=45,bottomMargin=50,title='Milana ERP Business Workflow and Navigation',author='Milana ERP documentation').build(story,onFirstPage=footer,onLaterPages=footer)
doc=pymupdf.open(pdf)
overflow=[]
for i,page in enumerate(doc):
    for block in page.get_text('blocks'):
        if block[0]<45 or block[2]>568 or block[1]<25 or block[3]>777:overflow.append({'page':i+1,'bounds':block[:4],'text':block[4][:80]})
    pix=page.get_pixmap(matrix=pymupdf.Matrix(1.2,1.2));pix.save(QA/f'page-{i+1:02}.png')
thumbs=[]
for i in range(len(doc)):
    im=Image.open(QA/f'page-{i+1:02}.png').convert('RGB');im.thumbnail((245,330));tile=Image.new('RGB',(265,355),'#dddddd');tile.paste(im,((265-im.width)//2,8));ImageDraw.Draw(tile).text((10,336),f'Page {i+1}',fill='black');thumbs.append(tile)
for start in range(0,len(thumbs),12):
    subset=thumbs[start:start+12];sheet=Image.new('RGB',(1060,355*((len(subset)+3)//4)),'white')
    for j,im in enumerate(subset):sheet.paste(im,((j%4)*265,(j//4)*355))
    sheet.save(QA/f'contact-{start//12+1}.png')
(QA/'qa.json').write_text(json.dumps({'pages':len(doc),'overflow':overflow},indent=2),encoding='utf8')
print(json.dumps({'pdf':str(pdf),'pages':len(doc),'overflow':overflow}))
