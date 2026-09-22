import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import ts from "typescript";

const sourcePath = path.resolve("src/lib/cuttingPassportDirectories.ts");
const tempPath = path.join(process.cwd(), `.cutting-passport-directory-hook-${process.pid}.cjs`);
const source = fs.readFileSync(sourcePath, "utf8");
fs.writeFileSync(tempPath, ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
}).outputText);

const require = createRequire(import.meta.url);
const React = require("react");
const { renderToStaticMarkup } = await import("react-dom/server");
const { useCuttingPassportDirectoryKeys } = require(tempPath);

function Probe({ open }) {
  const keys = useCuttingPassportDirectoryKeys(open);
  return React.createElement("output", { "data-production-orders": keys.productionOrders ?? "null", "data-operators": keys.operators ?? "null" });
}

const closed = renderToStaticMarkup(React.createElement(Probe, { open: false }));
assert.match(closed, /data-production-orders="null"/);
assert.match(closed, /data-operators="null"/);

const open = renderToStaticMarkup(React.createElement(Probe, { open: true }));
assert.match(open, /data-production-orders="\/api\/production-orders\?page_size=500"/);
assert.match(open, /data-operators="\/api\/cutting-passports\/operators"/);

fs.unlinkSync(tempPath);
console.log("Cutting passport directory hook execution passed: closed skips both keys; open enables both keys.");
