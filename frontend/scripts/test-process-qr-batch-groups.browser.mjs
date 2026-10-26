// Render the actual issued-label section with isolated fixtures; never contacts ERP.
import assert from "node:assert/strict";
import fs from "node:fs";
import { build } from "esbuild";
import { chromium } from "playwright";
import ts from "typescript";

const root = process.cwd();
const source = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functions = ast.statements.filter(node => ts.isFunctionDeclaration(node)
  && ["issuedBatchKey", "groupIssuedLabelsByBatch", "compareIssuedLabelOrder", "operationNumberForLabel",
    "compareGarmentSizes", "normalizedSizeName", "namedSizeRank"].includes(node.name?.text))
  .map(node => node.getText(ast)).join("\n");
const namedSizes = ast.statements.find(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(d => d.name.getText(ast) === "NAMED_SIZE_ORDER")).getText(ast);
const section = source.slice(source.indexOf("<section ref={issuedLabelsSectionRef}"), source.indexOf("<Modal", source.indexOf("<section ref={issuedLabelsSectionRef}")));
const entry = `
import React from "react"; import {createRoot} from "react-dom/client";
import {RefreshCw,Printer,Trash2,ChevronDown} from "lucide-react";
import en from "./src/lib/i18n/locales/en-supplemental";
import ru from "./src/lib/i18n/locales/ru-supplemental";
import uz from "./src/lib/i18n/locales/uz-supplemental";
${namedSizes}
${functions}
const lang=new URLSearchParams(location.search).get("lang")||"en", dict={en,ru,uz}[lang];
const t=(key,args={})=>Object.entries(args).reduce((v,[k,a])=>v.replaceAll("{"+k+"}",String(a)),dict[key]||key);
const issuedLabelsSectionRef=null,issuedLabelsLoading=false,preparingPrint=false,deletingSize=null;
const issuedSizeOrder=new Map([["122",0],["128",1]]),issuedOperationNumbers=new Map();
const activeIssuedLabels=[2,1].flatMap(batch=>["128","122"].flatMap(size=>[2,1].map(op=>{
 const id=batch*100+Number(size)*10+op;issuedOperationNumbers.set(id,op);
 return {id,factory_code:"MIL",production_order_id:420,production_batch_id:batch,batch_no:"0420-0"+batch,size,status:"available",copy_index:1,operation_name:"Process "+op};
})));
const orderedIssuedLabels=[...activeIssuedLabels].sort((a,b)=>compareIssuedLabelOrder(a,b,issuedSizeOrder,issuedOperationNumbers));
const issuedLabelsByBatch=groupIssuedLabelsByBatch(orderedIssuedLabels,[1,2].map(id=>({batchId:id,name:"Nastil "+id}))),editedIssuedLabels=[];
const printIssuedLabels=rows=>{window.printed=rows.map(row=>row.id)};
const deleteIssuedSize=(size,rows)=>{window.deleted=rows.map(row=>row.id)};
const openLabelCorrection=()=>{},canCorrectIssuedLabel=()=>true;
const IssuedProcessLabel=({label,operationNumber})=><article data-id={label.id}>{label.batch_no} / {label.size} / {operationNumber}</article>;
function App(){const [expandedIssuedBatches,setExpandedIssuedBatches]=React.useState(()=>new Set());return (${section});}
createRoot(document.getElementById("root")).render(<App/>);
`;
const built = await build({ stdin: { contents: entry, resolveDir: root, loader: "tsx" },
  bundle: true, write: false, format: "iife" });
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("http://localhost:3198/**", route => route.fulfill({ contentType: "text/html",
    body: `<div id="root"></div><script>${built.outputFiles[0].text.replaceAll("</script>", "<\\/script>")}</script>` }));
  for (const lang of ["en", "ru", "uz"]) {
    await page.goto(`http://localhost:3198/?lang=${lang}`);
    const batches = page.locator("[data-qr-batch]");
    await batches.nth(1).waitFor();
    assert.deepEqual(await batches.evaluateAll(nodes => nodes.map(n => n.dataset.qrBatch)), ["0420-01", "0420-02"]);
    const first = batches.first();
    const toggle=first.locator("button[aria-expanded]");
    assert.equal(await toggle.getAttribute("aria-expanded"),"false");
    assert.match(await toggle.innerText(),/Nastil 1/);
    assert.ok(!(await toggle.innerText()).includes("0420-01"));
    assert.equal(await first.locator("article").count(),0);
    await first.getByRole("button").nth(1).click();
    assert.equal((await page.evaluate(()=>window.printed)).length,4,"closed batch can print");
    assert.equal(await toggle.getAttribute("aria-expanded"),"false","printing does not expand");
    await toggle.focus(); await page.keyboard.press("Enter");
    assert.equal(await toggle.getAttribute("aria-expanded"),"true");
    assert.equal(await batches.nth(1).locator("button[aria-expanded]").getAttribute("aria-expanded"),"false");
    assert.deepEqual(await first.locator("[data-qr-size]").evaluateAll(nodes => nodes.map(n => n.dataset.qrSize)), ["122", "128"]);
    assert.deepEqual(await first.locator("article").allTextContents(),
      ["0420-01 / 122 / 1", "0420-01 / 122 / 2", "0420-01 / 128 / 1", "0420-01 / 128 / 2"]);
    const ids = await first.locator("article").evaluateAll(nodes => nodes.map(n => Number(n.dataset.id)));
    await first.getByRole("button").nth(1).click();
    assert.deepEqual(await page.evaluate(() => window.printed), ids);
    const size = first.locator("[data-qr-size]").first();
    await size.getByRole("button").nth(1).click();
    assert.deepEqual(await page.evaluate(() => window.printed), ids.slice(0, 2));
    await size.getByRole("button").first().click();
    assert.deepEqual(await page.evaluate(() => window.deleted), ids.slice(0, 2));
    assert.ok(!(await first.getByRole("button").nth(1).innerText()).includes("page.processQr"));
    await toggle.focus(); await page.keyboard.press("Space");
    assert.equal(await toggle.getAttribute("aria-expanded"),"false");
    assert.equal(await first.locator("article").count(),0);
    await batches.nth(1).locator("button[aria-expanded]").click();
    assert.equal(await first.locator("article").count(),0,"batches expand independently");
  }
  assert.deepEqual(errors, []);
  console.log("Actual batch/size sections, process sequence and scoped print/delete buttons pass in EN/RU/UZ.");
} finally { await browser.close(); }
