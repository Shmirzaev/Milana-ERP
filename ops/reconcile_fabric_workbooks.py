"""Build evidence-backed fabric reconciliation; never connects to a database."""
from collections import Counter, defaultdict
from decimal import Decimal
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/fabric-reconciliation'

def number(value):
    if value is None or value == '':
        return Decimal(0)
    return Decimal(str(value).replace('\u00a0','').replace(' ','').replace(',','.')).quantize(Decimal('0.0001'))

def key(value):
    return re.sub(r'\s+', '', str(value or '').upper())

def read_sources(evidence):
    records=[]
    # Dana's receipts belong to DANA DRAY SAF (19), confirmed by existing
    # batch identities; the Zuxra sheet belongs to Saff (3).
    for bi, si, supplier, label in [(0,0,2,'Dinar'),(1,0,1,'Samo'),(2,0,19,'Saff Dana'),(2,2,3,'Saff Zuxra')]:
        book=evidence[bi]; sheet=book['sheets'][si]
        cols = (3,4,5,9,2,10,11,12,13,6,7) if bi==0 else ((4,5,6,9,3,11,12,13,14,7,8) if bi==1 else (4,5,6,8,3,10,11,12,13,7,None))
        rolls,kg,batch,fabric,date,used_rolls,used_kg,left_rolls,left_kg,color_code,color=cols
        for row in sheet['rows']:
            v=row['values']
            if row['row'] <= (2 if bi==0 else 3 if bi==1 else 1):
                continue
            if not any(v[c] is not None for c in (rolls,kg,batch,used_rolls,used_kg)):
                continue
            try:
                for c in (rolls,kg,used_rolls,used_kg):number(v[c])
            except Exception:
                continue  # Header/summary text is preserved in raw evidence.
            r={'file':book['file'],'sheet':sheet['sheet'],'row':row['row'],'supplier_id':supplier,'group':label,
               'batch_no':str(v[batch]).strip() if v[batch] is not None else '', 'fabric':str(v[fabric] or '').strip(),
               'date':str(v[date] or '').strip(), 'received_rolls':number(v[rolls]),'received_kg':number(v[kg]),
               'used_rolls':number(v[used_rolls]),'used_kg':number(v[used_kg]),
               'remaining_rolls':number(v[rolls])-number(v[used_rolls]),'remaining_kg':number(v[kg])-number(v[used_kg]),
               'color_code':str(v[color_code] or '').strip(),'color':str(v[color] or '').strip() if color is not None else '',
               'cached_remaining_rolls':v[left_rolls],'cached_remaining_kg':v[left_kg], 'issues':[]}
            if v[rolls] is None or v[kg] is None:
                r['issues'].append('Receipt rolls or kg missing')
                if v[left_rolls] is not None:r['remaining_rolls']=number(v[left_rolls])
                if v[left_kg] is not None:r['remaining_kg']=number(v[left_kg])
            for col in (left_rolls,left_kg):
                formula=row['formulas'].get(chr(65+col),'')
                if '!' in formula or any(int(n)!=row['row'] for n in re.findall(r'\$?[A-Z]+\$?(\d+)',formula)):
                    r['issues'].append('Balance formula references another row or sheet')
            if r['remaining_kg']<0 or r['remaining_rolls']<0:
                r['issues'].append('Negative balance')
            for field, col in [('remaining_rolls',left_rolls),('remaining_kg',left_kg)]:
                if v[col] is not None and abs(number(v[col])-r[field])>Decimal('0.001'):
                    r['issues'].append(f'{field}: cached balance differs from receipt minus usage')
            if (r['remaining_kg']==0) != (r['remaining_rolls']==0):
                r['issues'].append('Zero kg and zero rolls disagree')
            if not r['batch_no']: r['issues'].append('Missing batch number')
            r['arithmetic_remaining_kg']=r['remaining_kg']
            # User clarification: the displayed remaining-kg column wins even
            # when its formula points at another receipt or conflicts with rolls.
            if v[left_kg] is not None:
                r['remaining_kg']=number(v[left_kg])
                r['balance_basis']='User-confirmed workbook remaining-kg cell'
            else:
                r['balance_basis']='Derived from receipt minus recorded usage; remaining-kg cell blank'
            records.append(r)
    return records

def main():
    evidence=json.loads((OUT/'source-workbooks.json').read_text(encoding='utf-8'))
    snapshot=json.loads((OUT/'production-snapshot.json').read_text(encoding='utf-8'))
    records=read_sources(evidence)
    (OUT/'source-records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    for group in dict.fromkeys(r['group'] for r in records):
        rows=[r for r in records if r['group']==group]
        print(group, 'rows',len(rows),'positive',sum(r['remaining_kg']>0 for r in rows),'kg',sum(r['remaining_kg'] for r in rows),'rolls',sum(r['remaining_rolls'] for r in rows))
    print('ISSUES',json.dumps([r for r in records if r['issues']],ensure_ascii=True,default=str))
    idx=defaultdict(list)
    for b in snapshot['batches']: idx[(b['supplier_id'],key(b['batch_no']))].append(b)
    counts=Counter()
    for r in records:
        matches=idx[(r['supplier_id'],key(r['batch_no']))]
        counts[('positive' if r['remaining_kg']>0 else 'zero',len(matches))]+=1
    print('MATCH COUNTS',counts)
    print('ERP TOTALS',[(sid,len(bs),sum(number(b['quantity']) for b in bs)) for sid in (1,2,3) if (bs:=[b for b in snapshot['batches'] if b['supplier_id']==sid and number(b['quantity'])>0])])

if __name__=='__main__': main()
