import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/processTimeline.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { processTimeline } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const cutting = { operation: "cutting", status: "completed", planned: 600, completed: 600, output_qty: 600 };
const sewing = { operation: "sewing", status: "in_progress", planned: 600, completed: 0, output_qty: 0, received_qty: 0 };
const stage = (rows, operation) => processTimeline(rows).find(row => row.operation === operation);
assert.equal(stage([cutting, sewing], "sewing").state, "waitingAcceptance", "auto-start is not acceptance");
assert.equal(stage([cutting, sewing], "printing").state, "skipped");
assert.equal(stage([], "printing").state, "notStarted");
assert.equal(stage([cutting, { ...sewing, received_qty: 600 }], "sewing").tone, "green");
assert.equal(stage([cutting, { ...sewing, received_qty: 100 }], "sewing").state, "partialAcceptance");
assert.equal(stage([cutting, { ...sewing, received_qty: 100 }], "sewing").tone, "yellow");
const partial = [{ ...cutting, status: "completed", completed: 498, output_qty: 498 }, { ...sewing, received_qty: 498 }];
assert.equal(stage(partial, "cutting").state, "completed", "closed Cutting stays complete below the original plan");
assert.equal(stage(partial, "cutting").tone, "green");
assert.equal(stage(partial, "cutting").output, 498, "closure does not invent output");
assert.equal(stage(partial, "cutting").planned, 600, "closure preserves the original plan");
for (const output of [300, 366, 588]) {
  const closed = { ...cutting, completed: output, output_qty: output, failed: 600 - output };
  assert.equal(stage([closed], "cutting").state, "completed");
  assert.equal(stage([{ ...closed, status: "in_progress" }], "cutting").state, "partial", "open Cutting remains partial");
  assert.equal(stage([{ ...closed, has_open_replacements: true }], "cutting").state, "partial", "replacement work remains visible");
  assert.equal(stage([{ ...closed, is_blocked: true }], "cutting").state, "blocked");
  assert.equal(stage([{ ...closed, status: "cancelled" }], "cutting").state, "cancelled");
  for (const operation of ["printing", "packaging", "storage_transfer"]) {
    assert.equal(stage([{ ...closed, operation }], operation).state, "partial", "other department output rules are unchanged");
  }
}
assert.equal(stage(partial, "sewing").state, "accepted");
assert.equal(stage(partial, "sewing").output, 0, "receipt does not mean sewn");
const printing = { operation: "printing", status: "in_progress", planned: 600, completed: 100, output_qty: 100 };
assert.equal(stage([cutting, printing, sewing], "sewing").ready, 100, "use actual prior stage; do not bypass printing");
assert.equal(stage([{ ...cutting, completed: 0, output_qty: 0, status: "waiting" }, sewing], "sewing").state, "notStarted");
assert.equal(stage([cutting, { ...sewing, received_qty: 600, overdue: true }], "sewing").state, "accepted", "overdue is separate from acceptance");
assert.equal(stage([cutting, { ...sewing, is_blocked: true }], "sewing").state, "blocked");
assert.equal(stage([cutting, { ...sewing, status: "cancelled" }], "sewing").state, "cancelled");
console.log("Process timeline: acceptance, partial receipts, output, routing and exception states passed.");
