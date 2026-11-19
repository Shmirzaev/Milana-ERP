import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(new URL("../src/lib/shipmentReportDates.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { shipmentReportDates } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);

for (const [instant, from, to] of [
  ["2026-11-11T18:59:59Z", "2026-11-11", "2026-11-11"],
  ["2026-11-11T19:00:00Z", "2026-11-12", "2026-11-12"],
  ["2026-12-31T19:00:00Z", "2027-01-01", "2027-01-01"],
]) assert.deepEqual(shipmentReportDates("day", new Date(instant)), { from, to });
for (const [instant, from, to] of [
  ["2026-11-11T10:00:00Z", "2026-11-01", "2026-11-30"],
  ["2026-02-01T00:00:00Z", "2026-02-01", "2026-02-28"],
  ["2028-02-01T00:00:00Z", "2028-02-01", "2028-02-29"],
  ["2026-12-31T19:00:00Z", "2027-01-01", "2027-01-31"],
]) assert.deepEqual(shipmentReportDates("month", new Date(instant)), { from, to });
console.log("Shipment report dates: Tashkent midnight, year rollover and leap months passed.");
