// Actual page/components with fixture APIs only; never connects to ERP data.
// Set PLAYWRIGHT_MODULE_PATH if Playwright is installed outside this project.
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import ts from "typescript";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const files = [
  ...["en", "ru", "uz"].map(lang => `lib/i18n/locales/${lang}-base.ts`),
  "lib/fabricScans.ts", "components/PageHeader.tsx", "components/PaginationControls.tsx",
  "components/FabricRollCamera.tsx", "app/(app)/fabric-scans/page.tsx",
];
const code = files.map(file => {
  const js = ts.transpileModule(fs.readFileSync(path.join(root, "src", file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  return `load(${JSON.stringify("@/" + file.replace(/\.tsx?$/, ""))}, ${JSON.stringify(js)});`;
}).join("\n");
const setup = `
const params = new URLSearchParams(location.search), lang = params.get('lang') || 'en';
window.calls = []; window.rows = []; window.fail = false; window.failReport = false; window.delay = 0;
window.me = {id:1, factory_code:'MIL', permissions: params.has('readonly') ? ['management.view'] : ['cutting.records']};
async function fixture(url) {
  if (window.failReport) throw Error('Offline');
  const day = new URL(url, location.origin).searchParams.get('report_date');
  const rows = window.rows.filter(r => r.report_date === day);
  const received = rows.filter(r => r.direction === 'received').length, returned = rows.length-received;
  return {report_date:day,department:'CUT',received,returned,total:rows.length,rows:[...rows].reverse(),
    summary:rows.length ? [{fabric_name:'Cotton jersey',batch_no:'FAB-2026',color:'Natural',received,returned}] : []};
}
function useFixtureSWR(key) {
 const stable = JSON.stringify(key), [state,setState] = React.useState({}), [version,setVersion] = React.useState(0);
 React.useEffect(()=>{let live=true;setState({});if(key)fixture(key[0]).then(data=>{if(live)setState({data})},error=>{if(live)setState({error})});return()=>{live=false}},[stable,version]);
 return {...state,isLoading:!!key&&!state.data&&!state.error,mutate:()=>setVersion(n=>n+1)};
}
const icon=p=>React.createElement('svg',{...p,width:16,height:16});
const modules={react:React,swr:{default:useFixtureSWR},'lucide-react':new Proxy({},{get:()=>icon}),
 '@/lib/auth':{useMe:()=>({me:window.me}),can:(me,...perms)=>perms.some(p=>me?.permissions.includes(p))},
 '@/lib/api':{fetcher:fixture,api:{post:async(url,body)=>{
   window.calls.push({url,body}); if(window.delay)await new Promise(resolve=>setTimeout(resolve,window.delay)); if(window.fail)throw Error('Offline');
   const existing = window.rows.find(r=>r.direction===body.direction && r.code===body.code);
   const row=existing||{id:window.rows.length+1,report_date:modules['@/lib/fabricScans'].tashkentDate(),direction:body.direction,
     fabric_name:'Cotton jersey',batch_no:'FAB-2026',color:'Natural',code:body.code,roll_number:Number(body.code.match(/R(\\d+)/)?.[1]||1),operator_name:'Test worker',scanned_at:new Date().toISOString()};
   if(!existing)window.rows.push(row);
   return {duplicate:!!existing,row};
 }}},
 '@/lib/i18n':{useT:()=>({lang,t:(key,args)=>{let s=modules['@/lib/i18n/locales/'+lang+'-base']?.default[key]||key;for(const[k,v]of Object.entries(args||{}))s=s.replaceAll('{'+k+'}',v);return s}})},
};
function load(name,code){const exports={};new Function('exports','require',code)(exports,name=>{if(!modules[name])throw Error('Missing '+name);return modules[name]});modules[name]=exports;}
${code}
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(modules['@/app/(app)/fabric-scans/page'].default));
`;
const cssDir = path.join(root, ".next/static/chunks");
const css = fs.readdirSync(cssDir).filter(file => file.endsWith(".css")).map(file => fs.readFileSync(path.join(cssDir, file), "utf8")).join("\n");
const server = http.createServer((req, res) => {
  if (["/react.js", "/react-dom.js"].includes(req.url)) {
    const pkg = req.url === "/react.js" ? "react" : "react-dom";
    res.setHeader("Content-Type", "text/javascript");
    res.end(fs.readFileSync(path.join(root, `node_modules/${pkg}/umd/${pkg}.development.js`))); return;
  }
  if (req.url === "/style.css") { res.setHeader("Content-Type", "text/css"); res.end(css); return; }
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(`<html><head><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="/style.css"></head><body><main id="root" style="padding:16px;max-width:1200px;margin:auto"></main><script src="/react.js"></script><script src="/react-dom.js"></script><script>${setup.replaceAll("</script>", "<\\/script>")}</script></body></html>`);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1366, height: 950 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
page.setDefaultTimeout(10000);
const url = `http://127.0.0.1:${server.address().port}`;
const out = path.join(root, "../outputs/fabric-scans-qa");
fs.mkdirSync(out, { recursive: true });
try {
  await page.goto(url);
  await page.getByText("No rolls scanned on this date.").waitFor();
  const input = page.getByLabel("Scan a roll QR code");
  await input.fill("B10-R1"); await input.press("Enter");
  await page.getByRole("status").filter({ hasText: "Saved" }).waitFor();
  assert.equal(await input.inputValue(), "");
  await input.fill("B10-R1"); await input.press("Enter");
  await page.getByRole("status").filter({ hasText: "Already recorded today" }).waitFor();
  assert.equal(await page.evaluate(() => window.rows.length), 1);
  await page.getByRole("radio", { name: "Returned from Cutting", exact: true }).check();
  await input.fill("B10-R1"); await input.press("Enter");
  await page.getByRole("status").filter({ hasText: "Saved" }).waitFor();
  assert.equal(await page.evaluate(() => window.rows.length), 2);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV" }).click();
  const download = await downloadEvent;
  await download.saveAs(path.join(out, "daily-report.csv"));
  assert.match(fs.readFileSync(path.join(out, "daily-report.csv"), "utf8"), /Cotton jersey.*FAB-2026.*"1","1"/);
  await page.screenshot({ path: path.join(out, "desktop.png"), fullPage: true });
  await page.evaluate(() => { window.fail = true; });
  await input.fill("B10-R2"); await input.press("Enter");
  await page.getByRole("alert").filter({ hasText: "Save was not confirmed" }).waitFor();
  await page.getByText("Not saved", { exact: false }).waitFor();
  await page.evaluate(() => { window.fail = false; });
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "Saved" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Retry", exact: true }).count(), 0);
  // No Enter or save button needed; the next scan can arrive during a slow save.
  await page.evaluate(() => { window.delay = 700; });
  await input.fill(" B10-R3 ");
  await page.waitForFunction(() => window.calls.some(c => c.body.code === 'B10-R3'));
  await input.fill("B10-R4"); await input.press("Enter");
  await page.waitForFunction(() => window.rows.some(r => r.code === 'B10-R4'));
  assert.equal(await input.evaluate(element => document.activeElement === element), true);
  await page.getByLabel("Date", { exact: true }).fill("2020-01-01");
  await page.getByText("No rolls scanned on this date.").waitFor();
  assert((await page.evaluate(() => window.calls)).every(call => call.url === "/api/fabric-scans"));
  for (const lang of ["ru", "uz"]) {
    await page.setViewportSize({ width: 390, height: 844 }); await page.goto(url + "?lang=" + lang);
    await page.locator("input[type=radio]").first().waitFor();
    assert.equal(await page.locator("body").innerText().then(text => text.includes("fabricScans.")), false);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No page overflow on phone");
    await page.screenshot({ path: path.join(out, lang + "-mobile.png"), fullPage: true });
  }
  await page.goto(url + "?readonly=1");
  await page.getByText("No rolls scanned on this date.").waitFor();
  assert.equal(await page.locator("input[type=radio]").count(), 0);
  await page.goto(url);
  await page.getByRole("button", { name: "Camera", exact: true }).click();
  await page.getByRole("alert").filter({ hasText: "Camera scanning is unavailable" }).waitFor();
  await page.getByRole("button", { name: "Close camera" }).click();
  // Simulate decoded video frames without requesting a physical camera.
  await page.addInitScript(() => {
    window.cameraCode = ""; window.cameraStarts = 0; window.cameraStops = 0;
    window.BarcodeDetector = class { async detect() { return window.cameraCode ? [{ rawValue: window.cameraCode }] : []; } };
    navigator.mediaDevices.getUserMedia = async () => {
      window.cameraStarts += 1;
      const stream = new MediaStream();
      stream.getTracks = () => [{ stop: () => { window.cameraStops += 1; } }];
      return stream;
    };
    HTMLMediaElement.prototype.play = async () => {};
  });
  await page.goto(url);
  await page.getByRole("button", { name: "Camera", exact: true }).click();
  await page.evaluate(() => { window.cameraCode = 'B10-R1'; });
  await page.waitForFunction(() => window.rows.length === 1);
  await page.waitForTimeout(700);
  assert.equal(await page.evaluate(() => window.calls.length), 1, "Held QR is submitted only once");
  await page.evaluate(() => { window.cameraCode = 'B10-R2'; });
  await page.waitForFunction(() => window.rows.length === 2);
  assert.equal(await page.evaluate(() => window.cameraStarts), 1, "Camera stays open between rolls");
  assert.equal(await page.evaluate(() => window.cameraStops), 0);
  await page.getByRole("radio", { name: "Returned from Cutting", exact: true }).check();
  await page.waitForTimeout(400);
  assert.equal(await page.evaluate(() => window.rows.length), 2, "Changing action alone must not scan the held roll");
  await page.evaluate(() => { window.cameraCode = ''; }); await page.waitForTimeout(250);
  await page.evaluate(() => { window.cameraCode = 'B10-R1'; });
  await page.waitForFunction(() => window.rows.length === 3);
  await page.evaluate(() => { window.cameraCode = 'B10-R2'; });
  await page.waitForFunction(() => window.rows.length === 4);
  await page.evaluate(() => { window.cameraCode = 'B10-R1'; });
  await page.getByRole("status").filter({ hasText: "Already recorded today" }).waitFor();
  assert.equal(await page.evaluate(() => window.rows.length), 4);
  await page.getByRole("button", { name: "Close camera" }).click();
  assert.equal(await page.evaluate(() => window.cameraStops), 1);
  assert.deepEqual(errors, []);
  console.log("PASS: continuous receive/return camera, held-label suppression, automatic keyboard scans, slow-save queue, duplicates, failed-save retry, daily filter, CSV, EN/RU/UZ, mobile overflow, read-only access, camera fallback; zero browser exceptions.");
} finally {
  await browser.close(); await new Promise(resolve => server.close(resolve));
}
