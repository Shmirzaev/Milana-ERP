// Isolated actual-page browser regression: fixture APIs only, no ERP server/data.
// Requires Chrome and Playwright (or PLAYWRIGHT_MODULE_PATH pointing to its install).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
const loadDependency = createRequire(import.meta.url);
const { chromium } = loadDependency(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const files = [
  'lib/i18n/locales/en-base.ts', 'lib/i18n/locales/en-supplemental.ts',
  'lib/numberInput.ts', 'lib/batchSerial.ts', 'lib/payrollScanStorage.ts', 'lib/modelCode.ts',
  'components/SearchableSelect.tsx', 'components/PayrollEmployeeSearch.tsx',
  'app/(app)/payroll/scan/page.tsx',
];
const code = files.map(file => {
  const js = ts.transpileModule(fs.readFileSync(path.join(root, 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return `load(${JSON.stringify('@/' + file.replace(/\.tsx?$/, ''))}, ${JSON.stringify(js)});`;
}).join('\n');
const setup = `
window.calls = []; window.searches = []; window.release = {};
const params = new URLSearchParams(location.search);
const employee = (id, name = 'Durdona Azamova') => ({type:'employee_payroll', employee_id:id, employee_no:'EMP-'+id, employee_name:name, department_name:id===2?'MIL Sewing B':'MIL Sewing A', position:'Operator'});
const icon = p => React.createElement('svg', {...p, width:16, height:16});
const modules = {
  react: React, 'react-dom': ReactDOM, 'lucide-react':new Proxy({}, {get:()=>icon}),
  '@/lib/modelImages': {storageThumbnailUrl:()=>null},
  '@/components/DialogProvider': {useDialogs:()=>({})},
  '@/components/PageHeader': {default:p=>React.createElement('h1',null,p.title)},
  '@/lib/auth': {useMe:()=>({me:{id:1}}), can:()=>params.get('readonly')!=='1'},
  '@/lib/i18n': {useT:()=>({lang:params.get('lang')||'en', t:(key,args)=>{
    let text=modules['@/lib/i18n/locales/en-supplemental']?.default[key]||modules['@/lib/i18n/locales/en-base']?.default[key]||key;
    for(const [k,v] of Object.entries(args||{}))text=text.replaceAll('{'+k+'}',v);return text;
  }})},
  '@/lib/api': {api:{
    get: async p=>{
      if(p.includes('/employees/search')){
        const q=new URL(p,location.origin).searchParams.get('q'); window.searches.push(q);
        if(q==='slow')return new Promise(resolve=>window.release.slow=()=>resolve({items:[employee(9,'Old result')],has_more:false}));
        if(q==='error')throw new Error('Fixture failure');
        if(q==='missing')return {items:[],has_more:false};
        return {items:[employee(1),employee(2)],has_more:q==='many'};
      }
      return employee(3,'Employee Number Lookup');
    },
    post: async (p,b)=>{
      window.calls.push({p,b});
      if(p!=='/api/payroll/scan/numeric-work')throw new Error('Unexpected payroll write');
      if(b.token==='200000002')await new Promise(resolve=>window.release.work=resolve);
      return {record:{id:Number(b.token),status:'accrued'}, work:{type:'process_payroll',label_id:b.token,quantity:10,rate_per_piece:100,currency:'UZS',operation_name:'Sewing',operation_code:'S1'}};
    }
  }}
};
function load(name,code){const exports={};new Function('exports','require',code)(exports,name=>{if(!modules[name])throw Error('Missing module '+name);return modules[name];});modules[name]=exports;}
${code}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(modules['@/app/(app)/payroll/scan/page'].default));
`;
const cssDir = path.join(root, '.next/static/chunks');
const css = fs.existsSync(cssDir) ? fs.readdirSync(cssDir).filter(f=>f.endsWith('.css')).map(f=>fs.readFileSync(path.join(cssDir,f),'utf8')).join('\n') : '';
const server = http.createServer((req,res)=>{
  if(['/react.js','/react-dom.js'].includes(req.url)) {
    const pkg=req.url==='/react.js'?'react':'react-dom';
    res.setHeader('Content-Type','text/javascript');
    res.end(fs.readFileSync(path.join(root,`node_modules/${pkg}/umd/${pkg}.development.js`))); return;
  }
  if(req.url==='/style.css'){res.setHeader('Content-Type','text/css');res.end(css);return;}
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><main id="root" style="padding:16px"></main><script src="/react.js"></script><script src="/react-dom.js"></script><script>${setup.replaceAll('</script>','<\\/script>')}</script></body></html>`);
});
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const url=`http://127.0.0.1:${server.address().port}`;
  try {
    await page.goto(url);
    const search=page.getByRole('combobox');
    const scanner=page.locator('input.font-mono');
    await search.fill('D');
    await page.getByText('Type at least 2 characters',{exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>window.searches.length),0);
    await search.fill('Durdona');
    await page.getByRole('option').nth(1).waitFor();
    assert.match(await page.getByRole('option').nth(1).innerText(),/EMP-2.*MIL Sewing B/s);
    await search.press('ArrowDown');await search.press('Enter');
    await page.waitForFunction(()=>document.activeElement?.classList.contains('font-mono'));
    assert.equal(await page.evaluate(()=>window.calls.length),0,'Selecting employee must not post payroll');
    await scanner.fill('200000001');
    await page.waitForFunction(()=>window.calls.length===1);
    assert.equal(await page.evaluate(()=>window.calls[0].b.employee_id),2);
    await page.getByText('Automatically saved 10 pcs for Durdona Azamova.').waitFor();
    // A late payroll completion must not steal focus while the operator searches.
    await scanner.fill('200000002');
    await page.waitForFunction(()=>!!window.release.work);
    await search.fill('slow');
    await page.waitForFunction(()=>!!window.release.slow);
    await page.evaluate(()=>window.release.work());
    await page.waitForFunction(()=>document.body.textContent.includes('2 saved'));
    assert(await search.evaluate(el=>el===document.activeElement));
    await search.fill('many');
    await page.getByText('More matches available. Type more of the name.').waitFor();
    await page.evaluate(()=>window.release.slow());
    assert.equal(await page.getByRole('option').filter({hasText:'Old result'}).count(),0);
    await page.getByRole('option').first().click();
    await page.waitForFunction(()=>document.activeElement?.classList.contains('font-mono'));
    // Repeating exactly the same query after selection must perform a fresh search.
    await search.fill('many');await page.getByRole('option').first().waitFor();
    await search.fill('missing');await page.getByText('No active employees found',{exact:true}).waitFor();
    await search.fill('error');await page.getByText('Employee search failed. Try typing again.',{exact:true}).waitFor();
    await search.fill('Durdona');await page.getByRole('option').first().waitFor();
    await search.press('Escape');
    await scanner.fill('EMP-3');await scanner.press('Enter');
    await page.getByText('Employee selected: Employee Number Lookup').waitFor();
    assert.equal(await page.evaluate(()=>window.calls.length),2);
    for(const lang of ['en','ru','uz']){
      await page.goto(url+'?lang='+lang);
      await page.setViewportSize({width:390,height:844});
      await page.getByRole('combobox').fill('Durdona');await page.getByRole('option').first().waitFor();
      assert(await page.getByRole('combobox').getAttribute('placeholder'));
      const box=await page.getByRole('listbox').boundingBox();
      assert(box.x>=0 && box.x+box.width<=390,'Search results fit phone width');
      if(process.env.PAYROLL_SEARCH_QA_OUTPUT && lang==='en') {
        fs.mkdirSync(process.env.PAYROLL_SEARCH_QA_OUTPUT,{recursive:true});
        await page.screenshot({path:path.join(process.env.PAYROLL_SEARCH_QA_OUTPUT,'employee-search-mobile.png'),fullPage:true});
        await page.setViewportSize({width:1280,height:900});
        await page.screenshot({path:path.join(process.env.PAYROLL_SEARCH_QA_OUTPUT,'employee-search-desktop.png'),fullPage:true});
      }
    }
    await page.goto(url+'?readonly=1');
    assert.equal(await page.getByRole('combobox').count(),0);
    assert.deepEqual(errors,[]);
    console.log('PASS: keyboard/mouse selection, no payroll on selection, numeric autosave for selected employee, employee-number entry, focus during late save, stale search isolation, repeated query, empty/error/retry, EN/RU/UZ and phone result bounds, permission visibility.');
  } finally {await browser.close();server.close();}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
