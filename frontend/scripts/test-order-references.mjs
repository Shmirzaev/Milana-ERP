import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const source = fs.readFileSync("src/lib/orderRef.ts", "utf8");
const javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { formatOrderReference, orderReference, rawOrderReference } = await import(
  `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`
);
assert.equal(formatOrderReference("PO-2026-000202"), "PO-0202");
assert.equal(formatOrderReference("SO-0606"), "SO-0606");
assert.equal(formatOrderReference("USL-2026-000001"), "USL-0001");
assert.equal(formatOrderReference("PO-2026-010000"), "PO-2026-010000");
assert.equal(formatOrderReference("PKG-2026-000123"), "PKG-2026-000123");
assert.equal(formatOrderReference("MANUAL-12"), "MANUAL-12");
assert.equal(formatOrderReference(null, "—"), "—");
assert.equal(orderReference({ production_no: "PO-2026-000202" }), "PO-0202");
const first = { production_no: "PO-2025-000001" };
const second = { production_no: "PO-2026-000001" };
assert.notEqual(rawOrderReference(first), rawOrderReference(second), "grouping keeps historical identities distinct");
assert.equal(first.production_no, "PO-2025-000001", "display helpers never mutate API rows");
console.log("Order display and historical identity checks passed.");
