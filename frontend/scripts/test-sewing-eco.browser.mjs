// Preview the compiled static app inside an intercepted browser context.
// This opens no frontend listener. API traffic is restricted to a disposable
// loopback QA backend; no production request or credential is used.
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
const root = path.resolve(import.meta.dirname, "../..");
const out = path.join(root, "outputs/preview");
const fixture = JSON.parse(fs.readFileSync(path.join(out, "fixture.json")));
const origin = "http://127.0.0.1:3197";
const backend = "http://127.0.0.1:8197";
const browser = await chromium.launch({headless: true, executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH});
try {
 const context = await browser.newContext({viewport:{width:1560,height:1100},timezoneId:"Asia/Tashkent", acceptDownloads:true});
 const auth = await context.request.post(backend+"/api/auth/token", {form:{username:"admin@example.com",password:"test-admin-password-123!"}});
 assert.equal(auth.status(),200);
 let token=(await auth.json()).access_token;
 const adminToken=token;
 const errors=[];
 await context.route("**/*", async route => {
   const url=new URL(route.request().url());
   assert.equal(url.origin,origin,"No external browser requests are permitted");
   if(url.pathname.startsWith("/api/")) {
     const response=await route.fetch({url:backend+url.pathname+url.search,headers:{...route.request().headers(),origin:"http://localhost:3000",authorization:`Bearer ${token}`}});
     return route.fulfill({response});
   }
   let file;
   if(url.pathname.startsWith("/_next/")) file=path.join(root,"frontend/.next",decodeURIComponent(url.pathname.slice(7)));
   else if(url.pathname==="/sewing-preview") file=path.join(out,"sewing.html");
   else if(url.pathname==="/sewing-preview.js") file=path.join(out,"sewing.js");
   else if(url.pathname.startsWith("/")) {
     const base=path.join(root,"frontend/.next/server/app",url.pathname);
     file=base+(url.searchParams.has("_rsc")?".rsc":".html");
     if(!fs.existsSync(file)) file=path.join(root,"frontend/public",url.pathname);
   }
   if(file && fs.existsSync(file) && fs.statSync(file).isFile()) {
     const extension=path.extname(file);
     const contentType=({".js":"application/javascript",".css":"text/css",".html":"text/html",".rsc":"text/x-component",".svg":"image/svg+xml",".woff2":"font/woff2",".png":"image/png",".ico":"image/x-icon"})[extension] || "application/octet-stream";
     return route.fulfill({body:fs.readFileSync(file),contentType});
   }
   // Disable prefetches for unrelated routes in this bounded preview.
   return route.fulfill({status:204});
 });
 const page=await context.newPage();
 page.on("pageerror",error=>errors.push(String(error)));
 await page.goto(origin+"/payroll/qr-control");
 await page.getByText("Partially scanned",{exact:true}).waitFor();
 assert.equal(await page.locator(".qr-order-white").count(),1);
 assert.equal(await page.locator(".qr-order-yellow").count(),1);
 assert.equal(await page.locator(".qr-order-green").count(),1);
 assert.equal(await page.locator(".qr-row-scanned").count(),0);
 await page.screenshot({path:path.join(out,"qr-control-collapsed.png"),fullPage:true});
 await page.locator(".qr-order-yellow button[aria-expanded]").click();
 assert.equal(await page.locator(".qr-row-scanned").count(),2);
 await page.screenshot({path:path.join(out,"qr-control-expanded.png"),fullPage:true});
 const mubinaAuth=await context.request.post(backend+"/api/auth/token", {form:{username:"mubina@example.com",password:"test-mubina-password-123!"}});
 assert.equal(mubinaAuth.status(),200);
 token=(await mubinaAuth.json()).access_token;
 await page.goto(origin+"/eco-fabric-transfers");
 await page.getByRole("heading",{name:"Fabric to Eco Cotton",exact:true}).waitFor();
 for(const code of [`B${fixture.firstBatch}-R1`,`B${fixture.firstBatch}-R2`,`B${fixture.secondBatch}-R1`]) {
   await page.getByLabel("Scan a roll QR code").fill(code);
   await page.getByLabel("Scan a roll QR code").press("Enter");
   await page.getByRole("status").filter({hasText:"Roll added to dispatch."}).waitFor();
 }
 await page.locator("main table tbody tr").nth(2).waitFor();
 await page.screenshot({path:path.join(out,"eco-dispatch-draft.png"),fullPage:true});
 await page.getByRole("button",{name:"Mark sent & download PDF",exact:true}).click();
 const download=page.waitForEvent("download");
 await page.getByRole("button",{name:"Mark sent & download PDF",exact:true}).last().click();
 await (await download).saveAs(path.join(out,"eco-dispatch.pdf"));
 await page.getByText("Dispatch saved. Fabric inventory updated.",{exact:true}).waitFor();
 await page.locator("details summary").first().click();
 await page.screenshot({path:path.join(out,"eco-dispatch-sent.png"),fullPage:true});
 await page.getByLabel("Return to fabric inventory",{exact:true}).check();
 await page.getByLabel("Scan a roll QR code").fill(`B${fixture.firstBatch}-R1`);
 await page.getByLabel("Scan a roll QR code").press("Enter");
 await page.getByText("Roll returned to fabric inventory.",{exact:true}).waitFor();
 await page.screenshot({path:path.join(out,"eco-return.png"),fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:path.join(out,"eco-mobile.png"),fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > window.innerWidth),false);
 await page.setViewportSize({width:1400,height:1050});
 token=adminToken;
 await page.goto(origin+"/sewing-preview");
 await page.getByRole("heading",{name:"Saved sewing records"}).waitFor();
 const history=page.locator("section").filter({has:page.getByRole("heading",{name:"Saved sewing records"})});
 await history.getByRole("button",{name:"Edit",exact:true}).click();
 await history.screenshot({path:path.join(out,"sewing-edit.png")});
 await history.getByLabel("Input quantity",{exact:true}).fill("90");
 await history.getByLabel("Sewn quantity",{exact:true}).fill("60");
 await history.getByLabel("Passed output",{exact:true}).fill("60");
 await history.getByRole("button",{name:"Save changes",exact:true}).click();
 await page.getByText("Record corrected; totals updated.",{exact:true}).waitFor();
 await history.screenshot({path:path.join(out,"sewing-saved.png")});
 await history.getByRole("button",{name:"Delete",exact:true}).click();
 await page.screenshot({path:path.join(out,"sewing-delete-confirmation.png"),fullPage:true});
 await page.getByRole("button",{name:"Delete",exact:true}).last().click();
 await page.getByText("Record deleted; totals updated.",{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 await page.waitForLoadState("networkidle");
 await context.unrouteAll({behavior:"ignoreErrors"});
 console.log("PASS: compiled QR/Eco pages and actual Sewing component; collapse/colors, API scan/send/PDF/return, edit/delete and mobile overflow");
} catch(error) {
 const pages=browser.contexts()[0]?.pages()||[];
 if(pages[0]) { await pages[0].screenshot({path:path.join(out,"browser-error.png"),fullPage:true}); console.error((await pages[0].locator("body").innerText()).slice(-5000)); }
 throw error;
} finally {await browser.close();}
