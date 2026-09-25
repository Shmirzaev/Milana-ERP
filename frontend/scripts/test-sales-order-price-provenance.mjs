import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/salesOrderPriceProvenance.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { copyPriceProvenance, submittedUnitPrice } = await import(
  `data:text/javascript;base64,${Buffer.from(js).toString("base64")}`
);

const catalogDefault = { unit_price: 12.5, price_edited: false };
const edited = { unit_price: 12.5, price_edited: true };
assert.equal(submittedUnitPrice(catalogDefault), null, "catalog prices must be revalidated by backend currency check");
assert.equal(submittedUnitPrice(edited), 12.5, "intentional price overrides must remain explicit");
assert.equal(submittedUnitPrice(copyPriceProvenance(edited)), 12.5,
  "size distribution must retain intentional price override provenance");
assert.equal(submittedUnitPrice(copyPriceProvenance(catalogDefault)), null,
  "size distribution must retain catalog price provenance");

const screen = readFileSync(new URL("../src/app/(app)/sales-orders/new/page.tsx", import.meta.url), "utf8");
assert.match(screen, /\.\.\.copyPriceProvenance\(base\)/);
assert.match(screen, /unit_price: submittedUnitPrice\(line\)/);
console.log("PASS: sales order price provenance survives size distribution and submission.");
