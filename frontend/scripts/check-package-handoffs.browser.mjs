// Real receiving/return components, isolated fixture APIs; no ERP data is touched.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const files = ['lib/orderRef.ts', 'lib/modelCode.ts', 'lib/variantDisplay.ts', 'lib/packageReturnText.ts',
  'components/Modal.tsx', 'components/ReturnPackages.tsx', 'components/ReceivePackages.tsx'];
const code = files.map(file => {
  const js = ts.transpileModule(fs.readFileSync(path.join(root, 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return `load(${JSON.stringify('@/' + file.replace(/\.tsx?$/, ''))}, ${JSON.stringify(js)});`;
}).join('\n');
const setup = `
window.calls=[]; window.reads=[]; window.confirmations=[]; window.fail=false;
const params=new URLSearchParams(location.search);
const icon=p=>React.createElement('svg',{...p,width:16,height:16});
const row={key:'run-5',code:'RUN-5',run_no:'PR-0005',package_ids:[11,12],count:2,quantity:40,
  packages:[{id:11,package_no:'PK-0011'},{id:12,package_no:'PK-0012'}],context:{production_no:'PO-1234',sales_order_no:'SO-1234',model_code:'MOD-100'}};
const modules={react:React,'lucide-react':new Proxy({},{get:()=>icon}),
  '@/lib/auth':{useMe:()=>({me:{id:1}}),can:()=>params.get('readonly')!=='1'},
  '@/lib/i18n':{useT:()=>({lang:params.get('lang')||'en',t:key=>({'common.search':'Search','common.previous':'Previous','common.close':'Close'}[key]||key)})},
  '@/components/DialogProvider':{useDialogs:()=>({ask:async message=>{window.confirmations.push(message);return true;}})},
  '@/components/ManualPackageReceipt':{default:()=>React.createElement('button',null,'Manual receipt')},
  '@/lib/api':{api:{post:async(p,b)=>{window.calls.push({p,b});if(window.fail)throw Error('Connection interrupted');return {};}}},
  swr:{default:key=>{React.useEffect(()=>{if(key)window.reads.push(key);},[key]);return {data:key?{rows:[row],has_more:false}:undefined,mutate:async()=>{}};},mutate:async()=>{}},
};
function load(name,code){const exports={};new Function('exports','require',code)(exports,name=>{if(!modules[name])throw Error('Missing module '+name);return modules[name];});modules[name]=exports;}
${code}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(modules['@/components/ReceivePackages'].default));
`;
const cssDir = path.join(root, '.next/static/css');
const css = fs.existsSync(cssDir) ? fs.readdirSync(cssDir).filter(f=>f.endsWith('.css')).map(f=>fs.readFileSync(path.join(cssDir,f),'utf8')).join('\n') : '';
const server = http.createServer((req,res)=>{
  if(['/react.js','/react-dom.js'].includes(req.url)) {
    const pkg=req.url==='/react.js'?'react':'react-dom';
    res.setHeader('Content-Type','text/javascript');res.end(fs.readFileSync(path.join(root,`node_modules/${pkg}/umd/${pkg}.development.js`)));return;
  }
  if(req.url==='/style.css'){res.setHeader('Content-Type','text/css');res.end(css);return;}
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><main id="root" style="padding:16px"></main><script src="/react.js"></script><script src="/react-dom.js"></script><script>${setup.replaceAll('</script>','<\\/script>')}</script></body></html>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1280,height:900}});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
const url=`http://127.0.0.1:${server.address().port}`;
const output=path.join(root,'../outputs/ui-qa');fs.mkdirSync(output,{recursive:true});
try {
  await page.goto(url);
  await page.getByRole('button',{name:'Receive packages',exact:true}).click();
  await page.getByRole('heading',{name:'Packages from Packaging'}).waitFor();
  await page.getByRole('textbox',{name:'Search order, model or package'}).fill('SO-1234');
  await page.getByRole('button',{name:'Search',exact:true}).click();
  await page.waitForFunction(()=>window.reads.some(p=>p.includes('q=SO-1234')));
  await page.getByRole('button',{name:'Receive packages',exact:true}).last().click();
  await page.waitForFunction(()=>window.calls.length===1);
  assert.deepEqual(await page.evaluate(()=>window.calls[0]),{p:'/api/packages/print-runs/receive',b:{code:'RUN-5'}});
  assert.match(await page.evaluate(()=>window.confirmations[0].message),/2 Packages.*40 Pieces/);
  await page.screenshot({path:path.join(output,'warehouse-receive-desktop.png')});
  await page.getByRole('button',{name:'Return to packaging',exact:true}).click();
  const submit=page.getByRole('button',{name:'Return to packaging',exact:true}).last();
  assert(await submit.isDisabled());
  await page.getByLabel('Reason for return').fill('Wrong quantity on the label');
  await page.evaluate(()=>window.fail=true);await submit.click();
  await page.getByRole('alert').filter({hasText:'Connection interrupted'}).waitFor();
  assert.equal(await page.getByLabel('Reason for return').inputValue(),'Wrong quantity on the label');
  await page.evaluate(()=>window.fail=false);await submit.click();
  await page.waitForFunction(()=>window.calls.length===3);
  assert.deepEqual(await page.evaluate(()=>window.calls[2]),{p:'/api/packages/return-to-packaging',b:{package_ids:[11,12],reason:'Wrong quantity on the label'}});
  for(const [lang,receive,returnLabel,reason] of [
    ['en','Receive packages','Return to packaging','Reason for return'],
    ['ru','Принять упаковки','Вернуть в упаковку','Причина возврата'],
    ['uz','Qadoqlarni qabul qilish','Qadoqlashga qaytarish','Qaytarish sababi'],
  ]) {
    await page.setViewportSize({width:390,height:844});await page.goto(url+'?lang='+lang);
    await page.getByRole('button',{name:receive,exact:true}).click();
    await page.getByRole('button',{name:returnLabel,exact:true}).click();
    await page.getByLabel(reason).fill('Incorrect label');
    const bounds=await page.getByRole('button',{name:returnLabel,exact:true}).last().boundingBox();
    assert(bounds.x>=0 && bounds.x+bounds.width<=391,lang+' return button fits phone');
    if(lang==='en') await page.screenshot({path:path.join(output,'warehouse-return-phone.png')});
  }
  await page.goto(url+'?readonly=1');assert.equal(await page.getByRole('button').count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS: searchable receipt without scanning, physical arrival confirmation, exact run receipt, return reason validation/error/retry, exact package selection, EN/RU/UZ phone fit, permission visibility.');
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
