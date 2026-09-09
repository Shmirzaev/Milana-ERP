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
  ...['en', 'ru', 'uz'].flatMap(lang => [`lib/i18n/locales/${lang}-base.ts`, `lib/i18n/locales/${lang}-supplemental.ts`]),
  'lib/numberInput.ts', 'lib/batchSerial.ts', 'lib/orderRef.ts', 'lib/modelCode.ts', 'lib/materialComposition.ts', 'lib/modelComposition.ts',
  'lib/modelVariants.ts', 'lib/modelPaidOperations.ts', 'lib/processQrLabelIdentity.ts', 'app/(app)/process-qr/page.tsx',
];
const code = files.map(file => {
  const js = ts.transpileModule(fs.readFileSync(path.join(root, 'src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return `load(${JSON.stringify('@/' + file.replace(/\.tsx?$/, ''))}, ${JSON.stringify(js)});`;
}).join('\n');
const setup = `
const params=new URLSearchParams(location.search), lang=params.get('lang')||'en';
window.calls=[]; window.release={}; window.failSizes=false;
const models=[
 {id:6919,code:'XJ3152-5412',sizes:[]},
 {id:6921,code:'XJ3152-5416',sizes:[{id:1,size:'XS'},{id:2,size:'S'}]},
 {id:6920,code:'XJ3152-5413',sizes:[]},
 {id:27,code:'XJ3152-V-5410',sizes:[]},
 {id:28,code:'XJ3152-V-5411',sizes:[]},
].map(m=>({...m,name:'Test robe',details_json:{general:{model_no:'XJ3152',variant_no:m.code.split('-').at(-1)}}}));
async function fixture(url){
 if(!url)return undefined;
 if(url.includes('/model-options'))return {items:models};
 if(url.endsWith('/process-qr-sizes')){
   const id=Number(url.split('/')[3]);
   if(id===27) await new Promise(resolve=>window.release.slow=resolve);
   if(window.failSizes)throw Error('Fixture failure');
   return {model_id:id,sizes:id===6920||id===28?[]:['48','50','52','54','56','58'],resolution:id===6920?'conflict':id===28?'missing':'inherited'};
 }
 if(url.match(/\\/api\\/models\\/\\d+$/))return models.find(m=>m.id===Number(url.split('/').at(-1)));
 if(url.includes('/issued-labels'))return {items:[]};
 return [];
}
function useFixtureSWR(key){
 const [state,setState]=React.useState({}), [version,setVersion]=React.useState(0);
 React.useEffect(()=>{let live=true;setState({});if(key)fixture(key).then(data=>{if(live)setState({data})},error=>{if(live)setState({error})});return()=>{live=false}},[key,version]);
 const mutate=React.useCallback(()=>setVersion(n=>n+1),[]);
 return {...state,isLoading:!!key&&!state.data&&!state.error,mutate};
}
const icon=p=>React.createElement('svg',{...p,width:16,height:16});
const modules={react:React,swr:{default:useFixtureSWR},qrcode:{default:{toDataURL:async()=>''}},
 'next/link':{default:({children,...p})=>React.createElement('a',p,children)},
 'lucide-react':new Proxy({},{get:()=>icon}),
 '@/components/PageHeader':{default:p=>React.createElement('header',null,React.createElement('h1',null,p.title),p.actions)},
 '@/components/Modal':{default:()=>null},
 '@/components/DialogProvider':{useDialogs:()=>({confirm:async()=>true})},
 '@/lib/auth':{useMe:()=>({me:{id:1,factory_code:'MIL'}})},
 '@/lib/api':{fetcher:fixture,api:{post:async(url,body)=>{window.calls.push({url,body});return {items:[]}},patch:async()=>{throw Error('Unexpected write')}}},
 '@/lib/i18n':{useT:()=>({lang,t:(key,args)=>{let s=modules['@/lib/i18n/locales/'+lang+'-supplemental']?.default[key]||modules['@/lib/i18n/locales/'+lang+'-base']?.default[key]||key;for(const[k,v]of Object.entries(args||{}))s=s.replaceAll('{'+k+'}',v);return s}})},
};
function load(name,code){const exports={};new Function('exports','require',code)(exports,name=>{if(!modules[name])throw Error('Missing module '+name);return modules[name]});modules[name]=exports;}
${code}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(modules['@/app/(app)/process-qr/page'].default));
`;
const cssDir=path.join(root,'.next/static/chunks');
const css=fs.existsSync(cssDir)?fs.readdirSync(cssDir).filter(f=>f.endsWith('.css')).map(f=>fs.readFileSync(path.join(cssDir,f),'utf8')).join('\n'):'';
const server=http.createServer((req,res)=>{
  if(['/react.js','/react-dom.js'].includes(req.url)){
    const pkg=req.url==='/react.js'?'react':'react-dom';res.setHeader('Content-Type','text/javascript');
    res.end(fs.readFileSync(path.join(root,`node_modules/${pkg}/umd/${pkg}.development.js`)));return;
  }
  if(req.url==='/style.css'){res.setHeader('Content-Type','text/css');res.end(css);return;}
  res.setHeader('Content-Type','text/html; charset=utf-8');
  res.end(`<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><main id="root" style="padding:16px"></main><script src="/react.js"></script><script src="/react-dom.js"></script><script>${setup.replaceAll('</script>','<\\/script>')}</script></body></html>`);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({channel:'chrome',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});
page.setDefaultTimeout(10000);
const errors=[];page.on('pageerror',error=>{errors.push(error.message);console.error(error.message);});
const url=`http://127.0.0.1:${server.address().port}`;
const out=path.join(root,'../outputs/size-qa');fs.mkdirSync(out,{recursive:true});
try{
  await page.goto(url);await page.getByRole('button',{name:'Manual order',exact:true}).first().click();
  await page.getByPlaceholder('Type variant number, model, or name...').fill('3152');
  const variant=page.locator('select').filter({has:page.locator('option[value="6919"]')});
  await page.getByText('Using the shared model sizes because this variant has no separate sizes.').waitFor();
  for(const size of ['48','50','52','54','56','58'])assert(await page.getByText(size,{exact:true}).count()>0);
  await page.screenshot({path:path.join(out,'inherited-desktop.png'),fullPage:true});
  await variant.selectOption('6921');await page.getByText('XS',{exact:true}).waitFor();
  assert.equal(await page.getByText('58',{exact:true}).count(),0,'Own sizes replace inherited sizes');
  await variant.selectOption('27');await page.waitForFunction(()=>!!window.release.slow);
  await variant.selectOption('6921');await page.getByText('XS',{exact:true}).waitFor();
  await page.evaluate(()=>window.release.slow());assert.equal(await page.getByText('58',{exact:true}).count(),0,'Late family response cannot leak across variants');
  await variant.selectOption('6920');await page.getByText('Other variants have different size sets.',{exact:false}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Issue labels',exact:true}).first().isDisabled(),true);
  await variant.selectOption('28');await page.getByText('This model variant has no configured sizes.',{exact:false}).waitFor();
  await page.evaluate(()=>{window.failSizes=true});await variant.selectOption('6919');
  await page.getByRole('alert').filter({hasText:'Could not load model sizes.'}).waitFor();
  await page.evaluate(()=>{window.failSizes=false});await page.getByTitle('Refresh data').click();
  await page.getByText('Using the shared model sizes because this variant has no separate sizes.').waitFor();
  assert.equal(await page.evaluate(()=>window.calls.length),0,'Viewing/resolving sizes must not create labels or records');
  for(const lang of ['ru','uz']){
    await page.setViewportSize({width:390,height:844});await page.goto(url+'?lang='+lang);
    await page.getByRole('button',{name:lang==='ru'?'Ручной заказ':"Qo‘lda buyurtma",exact:true}).first().click();
    await page.locator('input').first().fill('3152');
    await page.getByText('58',{exact:true}).waitFor();
    await page.screenshot({path:path.join(out,lang+'-mobile.png'),fullPage:true});
  }
  assert.deepEqual(errors,[]);console.log('Process QR size resolution browser checks passed.');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
