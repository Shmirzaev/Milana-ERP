// Read rendered old ERP model fields and their original data-URL images only.
import * as fs from 'node:fs/promises';
import { createHash } from 'node:crypto';

export async function makeAcquirer(tab, root) {
  const dir = root + '/evidence';
  const read = async name => JSON.parse(await fs.readFile(dir + '/' + name, 'utf8'));
  const log = await read('old-erp-photo-acquisition-20260908.json');
  const normalize = value => String(value || '').toUpperCase()
    .replace(/[АВСЕНКМОРТХУІЈ]/g, c => 'ABCEHKMOPTXYIJ'['АВСЕНКМОРТХУІЈ'.indexOf(c)])
    .replace(/[^\p{L}\p{N}]/gu, '');
  const csv = await fs.readFile(dir + '/models-still-missing-pictures-20260908.csv', 'utf8');
  const bases = new Set(csv.replace(/^\uFEFF/, '').trim().split(/\r?\n/).slice(1).map(l => normalize(l.split(',')[1])));
  const queue = (await read('old-models.json')).rows.filter(r => bases.has(normalize(r.model_no)))
    .sort((a,b) => Number(b.old_id)-Number(a.old_id));
  const next = () => queue.find(r => !log.some(x => x.old_id === r.old_id));
  async function one(row) {
    const url = new URL(row.edit_href, 'https://10.100.50.199:8443/uzerp/').href;
    if (await tab.url() !== url) await tab.goto(url);
    await tab.playwright.getByRole('cell', {name:row.model_no,exact:true}).first().waitFor({state:'visible',timeoutMs:10000});
    const dom = await tab.playwright.evaluate(() => ({
      url:location.href,
      rows:Array.from(document.querySelectorAll('tr')).filter(r => r.cells.length>=2 && r.cells[0].innerText.trim()==='Код Модели').map(r => r.cells[1].innerText.trim()),
      images:Array.from(document.images).map((i,index)=>({index,width:i.naturalWidth,height:i.naturalHeight,length:i.src.length,prefix:i.src.slice(0,30)}))
        .filter(i => i.width>256 && i.height>256 && i.prefix.startsWith('data:image/')),
    }));
    if (dom.url!==url || dom.rows.length!==1 || dom.rows[0]!==row.model_no) throw Error('Old ERP identity did not match');
    let result = {...row,url,captured_at:new Date().toISOString(),dom};
    if (dom.images.length===1) {
      const im=dom.images[0], parts=[];
      for(let offset=0;offset<im.length;offset+=100000) {
        parts.push(await tab.playwright.evaluate(({index,offset})=>document.images[index].src.slice(offset,offset+100000),{index:im.index,offset}));
      }
      const src=parts.join('');
      if(src.length!==im.length) throw Error('Truncated original');
      const bytes=Buffer.from(decodeURIComponent(src.split(',')[1]),'base64');
      const filename=row.model_no.replace(/[^A-Z0-9_-]/gi,'_')+'-'+row.old_id+(src.startsWith('data:image/png')?'.png':'.jpg');
      await fs.writeFile(dir+'/old-erp-model-originals/'+filename,bytes);
      result={...result,filename,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),width:im.width,height:im.height};
    }
    log.push(result);
    await fs.writeFile(dir+'/old-erp-photo-acquisition-20260908.json',JSON.stringify(log,null,2));
    return {model:row.model_no,images:dom.images.length,bytes:result.bytes};
  }
  return {
    status:()=>({checked:log.length,saved:log.filter(r=>r.filename).length,remaining:queue.filter(r=>!log.some(x=>x.old_id===r.old_id)).length}),
    async batch(maximum=12) {
      const completed=[],start=Date.now();
      while(completed.length<maximum && Date.now()-start<20000) {
        const row=next();if(!row)break;
        try {completed.push(await one(row));} catch(error){return {completed,error:String(error),next:row};}
      }
      return {completed};
    },
  };
}
