// Real React effects and rendered picker using the exact hook from CuttingPage.
// Only a disposable loopback harness is served; no ERP data or authentication.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import ts from "typescript";
import { build } from "esbuild";
import { chromium } from "playwright";

const source = fs.readFileSync("src/app/(app)/work-orders/[id]/cutting/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const helpers = [], names = new Set(["fmtQty", "compactParts", "batchAvailableQty", "fabricBatchCompactLabel"]);
let hook;
function visit(node) {
  if (ts.isFunctionDeclaration(node) && names.has(node.name?.text)) helpers.push(node.getText(ast));
  if (ts.isCallExpression(node) && node.expression.getText(ast) === "useEffect" &&
      node.getText(ast).includes("if (plannedMaterials.length > 0) return;") &&
      node.getText(ast).includes("fabricPickedManually")) hook = node.getText(ast);
  ts.forEachChild(node, visit);
}
visit(ast);
assert.ok(hook, "Actual default-source hook must be exercised");
const entry = `import React, {useState,useEffect} from "react";
import {createRoot} from "react-dom/client";
${helpers.join("\n")}
const central={id:2,item_id:4,item_sku:"FAB-COT-001",item_name:"Unrelated Milana fabric",batch_no:"MILANA-LOT",available_quantity:500,unit:"kg"};
const eco={id:7,item_id:5,item_sku:"ECO-DIRECT",item_name:"Planned Eco fabric",batch_no:"ECO-LOT",available_quantity:90,unit:"kg"};
function App(){
 const [ready,setReady]=useState(false),[fabricPickedManually,setFabricPickedManually]=useState(false);
 const [plannedId,setPlannedId]=useState(7),[form,setForm]=useState({fabric_batch_id:0,input_unit:"kg",waste_unit:"kg"});
 const po={fabric_batch_id:plannedId},plannedMaterials=[];
 // The model BOM contains only the unrelated central source. The explicitly
 // planned fabric arrives later from the authoritative ECO lookup.
 const fabricBatches=[central],allSearchableFabricBatches=ready?[central,eco]:[central];
 ${hook};
 const selected=allSearchableFabricBatches.find(row=>row.id===form.fabric_batch_id);
 return <main><input style={{width:560}} aria-label="Fabric" role="combobox" readOnly value={selected?fabricBatchCompactLabel(selected):""}/>
 <output data-testid="source">{form.fabric_batch_id}</output>
 <button onClick={()=>setReady(true)}>Eco lookup arrives</button>
 <button onClick={()=>{setReady(false);setPlannedId(8)}}>Planned source held</button>
 <button onClick={()=>{setFabricPickedManually(true);setForm(x=>({...x,fabric_batch_id:2}))}}>Manual choice</button>
 <button onClick={()=>{setFabricPickedManually(false);setReady(false);setPlannedId(0);setForm(x=>({...x,fabric_batch_id:0}))}}>Legacy no source</button>
 <button onClick={()=>{setFabricPickedManually(false);setReady(false);setPlannedId(7)}}>Saved source arrives late</button>
 </main>;
}
createRoot(document.getElementById("root")).render(<App/>);`;
const built = await build({ stdin: { contents: entry, loader: "tsx", resolveDir: process.cwd() },
  bundle: true, write: false, format: "iife", platform: "browser" });
const server = http.createServer((_request, response) => {
  response.setHeader("Content-Type", "text/html;charset=utf-8");
  response.end(`<html><body><div id="root"></div><script>${built.outputFiles[0].text.replaceAll("</script>", "<\\/script>")}</script></body></html>`);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined, headless: true });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.getByRole("combobox").waitFor();
  assert.equal(await page.getByRole("combobox").inputValue(), "", "Generic list arriving first cannot replace the planned source");
  await page.getByRole("button", { name: "Eco lookup arrives" }).click();
  await page.waitForFunction(() => document.querySelector("[data-testid=source]").textContent === "7");
  assert.match(await page.getByRole("combobox").inputValue(), /Planned Eco fabric.*90 kg/);
  await page.getByRole("button", { name: "Planned source held" }).click();
  await page.waitForFunction(() => document.querySelector("[data-testid=source]").textContent === "0");
  assert.equal(await page.getByRole("combobox").inputValue(), "", "Held/depleted planned fabric cannot fall back to another stock batch");
  await page.getByRole("button", { name: "Manual choice" }).click();
  await page.getByRole("button", { name: "Eco lookup arrives" }).click();
  assert.match(await page.getByRole("combobox").inputValue(), /Unrelated Milana fabric.*500 kg/, "Explicit manual choice remains intact");
  await page.getByRole("button", { name: "Legacy no source" }).click();
  await page.waitForFunction(() => document.querySelector("[data-testid=source]").textContent === "2");
  await page.getByRole("button", { name: "Saved source arrives late" }).click();
  await page.waitForFunction(() => document.querySelector("[data-testid=source]").textContent === "0");
  await page.getByRole("button", { name: "Eco lookup arrives" }).click();
  await page.waitForFunction(() => document.querySelector("[data-testid=source]").textContent === "7");
  const output = path.resolve("../outputs/eco-source-selection");
  fs.mkdirSync(output, { recursive: true });
  await page.screenshot({ path: path.join(output, "planned-eco-source.png") });
  assert.deepEqual(errors, []);
  console.log("Actual Cutting hook: delayed ECO source90kg, no unrelated default or held-source fallback, manual and legacy choices PASS.");
} finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
}
