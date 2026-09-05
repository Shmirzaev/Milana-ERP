// UI-only Telegram download helper, invoked from the persistent cua_repl.
import * as fs from 'node:fs/promises';

export async function makeDownloader(tab, cuaTab, root) {
  const directory = 'C:/Users/User/Downloads';
  const read = async name => JSON.parse(await fs.readFile(`${root}/evidence/${name}`, 'utf8'));
  const write = async (name, data) => fs.writeFile(`${root}/evidence/${name}`, JSON.stringify(data, null, 2));
  const plan = await read('telegram-photo-plan.json');
  const safety = new Map((await read('photo-safety-final-before.json')).models.map(r => [r.id, r]));
  const queue = plan.selected.filter(r => r.models.some(m => {
    const s = safety.get(m.id);
    return !String(s.general?.variant_no || '').trim() || s.independent_variant_url || !s.effective_variant_url;
  })).sort((a, b) => Number(b.source.id.split('-').pop()) - Number(a.source.id.split('-').pop()));
  const log = await read('telegram-downloads.json');
  let attempt;
  try { attempt = await read('telegram-download-attempt.json'); } catch { attempt = null; }
  const next = () => queue.find(r => !log.some(x => x.model_no === r.model_no));
  const persist = () => write('telegram-download-attempt.json', attempt);

  async function copy(row, name, existingPath) {
    const ext = name.match(/\.(png|jpe?g|webp)$/i)?.[0].toLowerCase();
    if (!ext) throw Error('Unexpected downloaded file type');
    const local = 'evidence/telegram-originals/' + row.source.id + ext;
    if (existingPath !== root + '/' + local) await fs.copyFile(existingPath || directory + '/' + name, root + '/' + local);
    const stat = await fs.stat(root + '/' + local);
    const record = { model_no: row.model_no, source: row.source, downloaded_name: name,
      local_path: local, bytes: stat.size };
    log.push(record);
    await write('telegram-downloads.json', log);
    attempt = null;
    await persist();
    return record;
  }

  async function recover() {
    if (!attempt || log.some(r => r.model_no === attempt.row.model_no)) return null;
    const dialogs = tab.playwright.getByRole('dialog');
    if (await dialogs.count()) {
      const name = await dialogs.getByRole('link', { name: 'Download', exact: true }).getAttribute('download');
      if (name !== attempt.row.source.name) throw Error('Unexpected open photo viewer');
      if (attempt.phase === 'lookup') {
        attempt.phase = 'submit';
        await persist();
        await dialogs.getByRole('link', { name: 'Download', exact: true }).click();
      }
      await dialogs.getByRole('button', { name: 'Close', exact: true }).click();
      await dialogs.waitFor({ state: 'hidden', timeoutMs: 10000 });
    }
    const fresh = (await fs.readdir(directory)).filter(n => !attempt.before.includes(n) && !n.endsWith('.crdownload'));
    if (attempt.phase === 'submit' && fresh.length === 1) return copy(attempt.row, fresh[0]);
    if (attempt.phase === 'submit') throw Error('Download outcome needs inspection: ' + JSON.stringify(fresh));
    attempt = null;
    await persist();
    return null;
  }

  async function fastClick(locator) {
    const rect = await locator.evaluate(el => { const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height,vw:innerWidth,vh:innerHeight}; });
    if (rect.w && rect.h && rect.x>0 && rect.y>0 && rect.x<rect.vw && rect.y<rect.vh) await cuaTab.click([rect.x,rect.y]);
    else {
      try { await locator.click(); } catch (error) {
        const fresh=await locator.evaluate(el => {const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height,vw:innerWidth,vh:innerHeight};});
        if (fresh.w && fresh.h && fresh.x>0 && fresh.y>0 && fresh.x<fresh.vw && fresh.y<fresh.vh) await cuaTab.click([fresh.x,fresh.y]);
        else throw error;
      }
    }
  }

  async function one() {
    if (attempt) {
      const recovered = await recover();
      if (recovered) return recovered;
    }
    const stages = []; let stamp = Date.now(); const mark = name => { stages.push([name, Date.now()-stamp]); stamp=Date.now(); };
    const row = next();
    if (!row) return null;
    const reused = log.find(x => x.source.id === row.source.id);
    if (reused) return copy(row, reused.downloaded_name, root + '/' + reused.local_path);
    attempt = { row, before: await fs.readdir(directory), phase: 'lookup', started_at: new Date().toISOString() };
    await persist();
    const message = row.source.id.replace('shared-mediamessage-', 'message-');
    const icon = tab.playwright.locator('#' + message + ' .file-icon-container');
    if (await icon.count()) {
      for (let i=0;i<4;i++) {
        const box=await icon.evaluate(el=>({y:el.getBoundingClientRect().y,h:innerHeight}));
        if (box.y>80 && box.y<box.h-140) break;
        await cuaTab.scroll([1200,440],box.y<80?'up':'down',Math.max(1,Math.min(8,Math.round(Math.abs(box.y-box.h/2)/(box.h*.85)))));
        await cuaTab.getAXState({emit:false});
      }
    }
    if (await icon.count() === 0 || !(await icon.evaluate(el => {const r=el.getBoundingClientRect(); return r.top>80 && r.bottom<innerHeight-80;}))) {
      const input = tab.playwright.getByPlaceholder('Search', { exact: true }).nth(1);
      await fastClick(input); mark('focus');
      await input.fill(row.source.name); mark('fill');
      const variant = row.source.name.match(/V[ _-]*(\d+)/i);
      const pattern = new RegExp(variant ? 'V[ _-]*' + variant[1]
        : row.model_no.replace(/([A-Z]+)(\d+)/, '$1[ _-]*$2'), 'i');
      const result = tab.playwright.locator('.MiddleSearchResult').filter({ hasText: pattern }).first();
      await result.waitFor({ state: 'visible', timeoutMs: 12000 });
      mark('search'); await fastClick(result); mark('jump');
      await icon.waitFor({ state: 'visible', timeoutMs: 10000 });
      await cuaTab.getAXState({ emit: false });
    }
    mark('ready'); await fastClick(icon); mark('viewer');
    const dialog = tab.playwright.getByRole('dialog');
    const download = dialog.getByRole('link', { name: 'Download', exact: true });
    const name = await download.getAttribute('download', { timeoutMs: 12000 });
    if (name !== row.source.name) throw Error('Filename mismatch: ' + name + ' vs ' + row.source.name);
    attempt.phase = 'submit';
    await persist();
    await download.downloadMedia({ timeoutMs: 12000 }); mark('download');
    await cuaTab.pressKey('Escape');
    await dialog.waitFor({ state: 'hidden', timeoutMs: 10000 });
    const fresh = (await fs.readdir(directory)).filter(n => !attempt.before.includes(n) && !n.endsWith('.crdownload'));
    if (fresh.length !== 1) throw Error('Download outcome needs inspection: ' + JSON.stringify(fresh));
    const saved = await copy(row, fresh[0]); mark('save'); return {...saved, timings: stages};
  }

  return {
    status: () => ({ saved: log.length, total: queue.length, next: next()?.source, attempt: attempt?.phase }),
    async batch(maximum = 8) {
      const start = Date.now();
      const completed = [];
      for (let i = 0; i < maximum && Date.now() - start < 30000; i++) {
        try {
          const saved = await one();
          if (!saved) break;
          completed.push({model:saved.model_no,timings:saved.timings});
        } catch (error) {
          return { completed, saved: log.length, total: queue.length, error: String(error),
            phase: attempt?.phase, next: next()?.source,
            dialogs: await tab.playwright.getByRole('dialog').count() };
        }
      }
      return { completed, saved: log.length, total: queue.length };
    },
  };
}
