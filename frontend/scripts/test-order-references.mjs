import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const source = fs.readFileSync("src/lib/orderRef.ts", "utf8");
const javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText;
const { formatOrderReference, orderReference, rawOrderReference } = await import(
  `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`
);
assert.equal(formatOrderReference("PO-0202"), "PO-0202");
assert.equal(formatOrderReference("SO-0606"), "SO-0606");
assert.equal(formatOrderReference("USL-0001"), "USL-0001");
assert.equal(formatOrderReference("PO-2026-010000"), "PO-2026-010000");
assert.equal(formatOrderReference("PKG-2026-000123"), "PKG-2026-000123");
assert.equal(formatOrderReference("MANUAL-12"), "MANUAL-12");
assert.equal(formatOrderReference(null, "—"), "—");
assert.equal(orderReference({ production_no: "PO-0202" }), "PO-0202");
const first = { production_no: "PO-2025-000001" };
const second = { production_no: "PO-2026-000001" };
assert.notEqual(rawOrderReference(first), rawOrderReference(second), "grouping keeps historical identities distinct");
assert.notEqual(orderReference(first), orderReference(second), "the browser must not guess canonical numbers for legacy collisions");
assert.equal(first.production_no, "PO-2025-000001", "display helpers never mutate API rows");

// Exercise the actual QR encoder and printed label component with canonical API
// data, rather than a parallel formatter that could hide stale QR references.
const pageSource = fs.readFileSync("src/app/(app)/process-qr/page.tsx", "utf8");
const pageAst = ts.createSourceFile("page.tsx", pageSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const functions = ["compactQrValue", "compactQrNumber", "workOrderIdForOperation", "compactWorkPayload", "sewingLinePrintText", "IssuedProcessLabel", "LabelLine"];
const selectedSource = functions.map(name => {
  const declaration = pageAst.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === name);
  assert.ok(declaration, `Missing production function ${name}`);
  return declaration.getText(pageAst);
}).join("\n");
const compiled = ts.transpileModule(selectedSource, {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS },
}).outputText;
const { compactWorkPayload, IssuedProcessLabel } = new Function(
  "React", "useT", "orderReference", "FACTORY_SHORT_CODES", "VALID_SECTIONS", "SECTION_BADGES", "paidSectionLabel", "ProcessQrImage", "Pencil",
  `${compiled}\nreturn { compactWorkPayload, IssuedProcessLabel };`,
)(React, () => ({ t: key => key, lang: "en" }), orderReference, { milana: "MIL" }, ["sewing"], { sewing: "" }, value => value,
  ({ payload }) => React.createElement("span", { "data-qr": payload }), () => null);
const process = { production_order_id: 42, production_no: "PO-0202", sales_order_id: 6, sales_order_no: "SO-0606", model_id: 3, model_code: "XJ5614", stages: [] };
const fields = compactWorkPayload(process, { batchId: 7, batchNo: "1", batchIndex: 1 }, { section: "sewing", code: "OP-0001", name: "Chontak", sewingFactory: "milana" }, { id: 1, code: "SEW-01", name: "Line" }, 20, 250, "UZS", "48", 1, "LEGACY-IMMUTABLE-UID").split("*");
assert.equal(fields[2], "PO-0202");
assert.equal(fields[15], "SO-0606");
assert.equal(fields[18], "LEGACY-IMMUTABLE-UID", "physical scan identity survives renumbering");
const label = { ...process, operation_section: "sewing", operation_name: "Chontak", operation_code: "OP-0001", batch_no: "1", size: "48", quantity: 20, rate_per_piece: 250, currency: "UZS", qr_token: "200000123" };
const printed = renderToStaticMarkup(React.createElement(IssuedProcessLabel, { label, operationNumber: 1 }));
assert.ok(printed.includes("SO-0606"), "printed label includes canonical order reference");
assert.ok(printed.includes('data-qr="200000123"'), "numeric QR continues to resolve the same issued label");
assert.ok(!printed.includes("2026-000606"));
console.log("Canonical order rendering, QR payload, printed label and collision identity checks passed.");
