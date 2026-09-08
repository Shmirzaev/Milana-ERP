import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const runtime = fs.readFileSync("src/lib/i18n.tsx", "utf8");
const exports = {};
vm.runInNewContext(ts.transpile(fs.readFileSync("src/lib/stocktakeText.ts", "utf8"), { module: ts.ModuleKind.CommonJS }), { exports });
const text = exports.stocktakeText;
for (const lang of ["en", "ru", "uz"]) {
  const path = `src/lib/i18n/locales/${lang}-base`;
  assert(runtime.includes(`./i18n/locales/${lang}-base`), `${lang}: locale must be used at runtime`);
  const messages = {};
  vm.runInNewContext(ts.transpile(fs.readFileSync(`${path}.ts`, "utf8"), { module: ts.ModuleKind.CommonJS }), { exports: messages });
  assert.equal(messages.default["nav.stocktake"], text[lang].title, `${lang}: visible navigation matches page title`);
  assert.deepEqual(Object.keys(text[lang]).sort(), Object.keys(text.en).sort(), `${lang}: complete count workflow translations`);
  assert(Object.values(text[lang]).every(value => typeof value === "string" && value.trim()));
}
console.log("Inventory-count runtime navigation and workflow translations passed.");
