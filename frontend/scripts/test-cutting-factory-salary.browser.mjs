import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium } from "playwright";

const root = process.cwd();
const result = await build({
  stdin: {
    contents: `import React from "react";import {createRoot} from "react-dom/client";
      import Factory from "./src/components/CuttingSewingFactory";
      import Salary from "./src/components/payroll/SewingSalarySummaryTable";
      const rows=[{employee_id:1,employee_name:"Worker A",master_id:11,master_name:"Own Master",currency:"UZS",record_count:2,quantity:2,total_amount:350,daily_amounts:{"2026-10-20":350}},
                  {employee_id:2,employee_name:"Worker B",master_id:12,master_name:"Other Master",currency:"UZS",record_count:1,quantity:1,total_amount:70,daily_amounts:{"2026-10-20":70}}];
      createRoot(document.getElementById("root")).render(<>
        <Factory workOrderId={9} factory="MIL" locked={window.locked} batches={window.batches} onSaved={async()=>{window.refreshed++}}/>
        <Salary rows={rows} days={["2026-10-20"]} lang={window.lang} t={key=>key}/></>);`,
    resolveDir: root, loader: "tsx",
  },
  bundle: true, write: false, format: "iife", jsx: "automatic",
  plugins: [{ name: "fixtures", setup(builder) {
    const stubs = {
      "@/lib/i18n": `export const useT=()=>({lang:window.lang,t:key=>key});`,
      "@/lib/api": `export const api={patch:async(path,body)=>{window.calls.push({path,body});if(window.reject)throw Error("Sewing output recorded");return {changed:true};}};`,
    };
    builder.onResolve({ filter: /^@\// }, args => args.path in stubs ? { path: args.path, namespace: "fixtures" } : undefined);
    builder.onLoad({ filter: /.*/, namespace: "fixtures" }, args => ({ contents: stubs[args.path], loader: "tsx", resolveDir: root }));
  } }],
});
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("http://localhost:3197/**", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  const batches = [
    { id: 1, batch_no: "Nastil 1", bundle_count: 1, sewing_output_recorded: true },
    { id: 2, batch_no: "Nastil 2", bundle_count: 1, sewing_output_recorded: false },
    { id: 3, batch_no: "Nastil 3", bundle_count: 1, sewing_output_recorded: false },
  ];
  async function load(lang = "en", locked = false, reject = false, batchRows = batches) {
    await page.goto("http://localhost:3197/");
    await page.evaluate(values => Object.assign(window, values, { calls: [], refreshed: 0 }), { lang, locked, reject, batches: batchRows });
    await page.addScriptTag({ content: result.outputFiles[0].text });
  }
  await load();
  await page.getByRole("button", { name: "Change factory" }).click();
  await page.getByLabel("field.sewingFactory", { exact: true }).selectOption("BST");
  await page.getByRole("button", { name: "btn.save", exact: true }).click();
  await page.waitForFunction(() => window.refreshed === 1);
  assert.deepEqual(await page.evaluate(() => window.calls), [{ path: "/api/work-orders/9/sewing-factory", body: { sewing_factory_code: "BST" } }]);
  const table = page.locator(".no-print table");
  assert.deepEqual(await table.locator("tbody th").allTextContents(), ["Master: Own Master", "Master: Other Master"]);
  assert.match(await table.innerText(), /Worker A[\s\S]*350 UZS/);
  await load("en", false, true);
  await page.getByRole("button", { name: "Change factory" }).click();
  await page.getByLabel("field.sewingFactory", { exact: true }).selectOption("ECO");
  await page.getByRole("button", { name: "btn.save", exact: true }).click();
  await page.getByRole("status").filter({ hasText: "Sewing output recorded" }).waitFor();
  assert.equal(await page.evaluate(() => window.refreshed), 0);
  for (const lang of ["en", "ru", "uz"]) {
    await load(lang, true);
    assert.equal(await page.getByRole("button").first().isDisabled(), false);
    await page.getByRole("button").first().click();
    assert.equal(await page.getByRole("radio").first().isDisabled(), true);
    assert.equal(await page.getByRole("checkbox", { name: /Nastil 1/ }).isDisabled(), true);
    assert.equal(await page.getByRole("button", { name: "btn.save", exact: true }).isDisabled(), true);
    await page.getByRole("checkbox", { name: "Nastil 2", exact: true }).check();
    await page.getByRole("checkbox", { name: "Nastil 3", exact: true }).check();
    await page.getByLabel("field.sewingFactory", { exact: true }).selectOption("BST");
    await page.getByRole("button", { name: "btn.save", exact: true }).click();
    await page.waitForFunction(() => window.refreshed === 1);
    assert.deepEqual(await page.evaluate(() => window.calls), [{ path: "/api/work-orders/9/sewing-factory", body: { sewing_factory_code: "BST", production_batch_ids: [2, 3] } }]);
    await load(lang, true, false, [batches[0]]);
    assert.equal(await page.getByRole("button").first().isDisabled(), true);
    assert.equal(await page.locator("select").count(), 0);
  }
  assert.deepEqual(errors, []);
  console.log("Whole-order and selected-Nastil factory save, output rejection, scope locks, EN/RU/UZ and salary Master grouping passed.");
} finally { await browser.close(); }
