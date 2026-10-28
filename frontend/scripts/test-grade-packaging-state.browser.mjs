import assert from "node:assert/strict";
import { build } from "esbuild";
import { chromium } from "playwright";

// Isolated component fixture. Every API call is synthetic; no ERP runtime or
// database is contacted. The released entry/locale test is retained separately.
const root = process.cwd();
const stubs = {
  "@/lib/auth": `export const useMe=()=>({me:{id:9,permissions:['packaging.packages']}});export const can=()=>true;`,
  "@/lib/i18n": `export const useT=()=>({lang:'en'});`,
  "@/lib/api": `export const fetcher=async()=>({needs_size_entry:false,total:5,version:'a'.repeat(64),sizes:[{size:'S',accepted:2,packed:0,remaining:2},{size:'M',accepted:3,packed:0,remaining:3}]});export const api={};`,
  "@/components/PendingPackageWorkflow": `export default function Pending(){return null;}`,
  "@/lib/packageWorkflow": `export const postPackageWorkflow=async(path,body)=>{window.calls.push({path,body});if(window.hold)await new Promise(resolve=>window.finish=resolve);if(window.refuse)throw Error('Synthetic refusal');return {id:1};};`,
};
const bundle = await build({ stdin: {
  contents: `import React from 'react';import {createRoot} from 'react-dom/client';import Packaging from './src/components/FirstGradePackaging';const root=createRoot(document.getElementById('root'));window.renderPackaging=props=>root.render(<Packaging productionOrderId={301} batchId={139} modelId={1} color="White" onChanged={async()=>{}} {...props}/>);window.renderPackaging({});`,
  resolveDir: root, loader: "tsx",
}, bundle: true, write: false, format: "iife", jsx: "automatic", plugins: [{ name: "fixtures", setup(builder) {
  builder.onResolve({ filter: /^@\// }, args => args.path in stubs ? { path: args.path, namespace: "fixtures" } : undefined);
  builder.onLoad({ filter: /.*/, namespace: "fixtures" }, args => ({ contents: stubs[args.path], loader: "tsx", resolveDir: root }));
} }] });
const browser = await chromium.launch({ channel: process.platform === "win32" ? "chrome" : undefined });
try {
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("http://localhost:3199/**", route => route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' }));
  await page.goto("http://localhost:3199/");
  await page.evaluate(() => Object.assign(window, { calls: [], hold: false, refuse: false }));
  await page.addScriptTag({ content: bundle.outputFiles[0].text });
  async function open() {
    await page.getByRole("button", { name: "1st Grade — singles" }).click();
    await page.getByLabel("Singles to pack S").waitFor();
  }
  const first = page.getByLabel("1st Grade total (kg)", { exact: true });
  const second = page.getByLabel("2nd Grade total (kg)", { exact: true });
  await open();
  await first.fill("0.0001");
  await page.getByLabel("Singles to pack S").fill("2");
  assert.equal(await page.getByRole("button", { name: "Create singles and labels (2/200)" }).isDisabled(), true, "Refuse weight below a positive share per piece");
  await first.fill("0.5001");
  await second.fill("1.25");
  await page.getByLabel("Grade", { exact: true }).selectOption("second_grade");
  assert.equal(await first.inputValue(), "0.5001");
  assert.equal(await second.inputValue(), "1.25");
  assert.equal(await page.getByLabel("Singles to pack S").inputValue(), "", "Grade switch clears selected quantities");
  await page.getByLabel("Singles to pack M").fill("3");
  await page.evaluate(() => { window.hold = true; });
  const submit = page.getByRole("button", { name: "Create packages and labels (3)" });
  await submit.click();
  await page.waitForFunction(() => window.calls.length === 1 && Boolean(window.finish));
  assert.equal(await submit.isDisabled(), true);
  for (const input of await page.locator("input, select").all()) assert.equal(await input.isDisabled(), true, "Inputs disabled while pending");
  await page.locator("form").evaluate(form => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  assert.equal(await page.evaluate(() => window.calls.length), 1, "Busy handler refuses a duplicate submit");
  await page.evaluate(() => { window.hold = false; window.finish(); });
  await page.waitForFunction(() => document.querySelector('[aria-label="2nd Grade total (kg)"]')?.value === "");
  assert.equal(await first.inputValue(), "0.5001", "Saving second grade retains first-grade total");
  assert.equal(await page.getByLabel("Singles to pack M").inputValue(), "");
  const saved = await page.evaluate(() => window.calls[0].body.packages);
  assert.equal(saved.length, 1);
  assert.equal(saved[0].stock_kind, "second_grade");
  assert.equal(saved[0].weight_kg, 1.25);
  assert.equal(saved[0].items[0].quantity, 3);
  await second.fill("1.5");
  await page.getByLabel("Singles to pack M").fill("2");
  await page.evaluate(() => { window.refuse = true; });
  await page.getByRole("button", { name: "Create packages and labels (2)" }).click();
  await page.getByRole("status").filter({ hasText: "Synthetic refusal" }).waitFor();
  assert.equal(await second.inputValue(), "1.5");
  assert.equal(await page.getByLabel("Singles to pack M").inputValue(), "2");
  assert.equal(await page.getByRole("button", { name: "Create packages and labels (2)" }).isEnabled(), true, "Refusal releases busy state");
  const selection = {};
  for (const [field, value] of [["productionOrderId", 302], ["batchId", 140], ["modelId", 2], ["color", "Blue"]]) {
    await first.fill("2.5"); await second.fill("3.5");
    selection[field] = value;
    await page.evaluate(props => window.renderPackaging(props), selection);
    await page.waitForFunction(() => document.querySelectorAll("input").length === 0);
    await open();
    assert.equal(await first.inputValue(), "", `${field} resets first grade`);
    assert.equal(await second.inputValue(), "", `${field} resets second grade`);
    assert.equal(await page.getByLabel("Grade", { exact: true }).inputValue(), "first_grade", `${field} resets grade`);
    assert.equal(await page.getByLabel("Singles to pack M").inputValue(), "", `${field} resets counts`);
    assert.equal(await page.getByText("Synthetic refusal").count(), 0, `${field} clears old refusal`);
  }
  assert.deepEqual(errors, []);
  console.log("Grade state fixture passed: positive-weight refusal; separate grade totals; busy duplicate refusal; success/failure retention; order/batch/model/color keyed resets.");
} finally {
  await browser.close();
}
