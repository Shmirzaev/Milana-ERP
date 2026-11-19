import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import ts from "typescript";

const exports = {};
const source = fs.readFileSync(new URL("../src/lib/payrollPeriodDates.ts", import.meta.url), "utf8");
new Function("exports", ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }))(exports);

test("payroll period follows factory calendar at browser-local month boundary", () => {
  const now = new Date("2026-10-31T20:30:00Z"); // 1 November in the factory
  assert.equal(exports.monthStart(now), "2026-11-01");
  assert.equal(exports.monthEnd(now), "2026-11-30");
  assert.equal(exports.factoryPeriodIso("2026-11-01"), "2026-10-31T19:00:00.000Z");
  assert.equal(exports.factoryPeriodIso("2026-11-30", true), "2026-11-30T18:59:59.000Z");
  assert.equal(exports.formatFactoryPeriodDate("2026-10-31T19:00:00Z", "en-US"), "11/1/2026");
  assert.equal(exports.formatFactoryPeriodDate("2026-11-30T18:59:59Z", "en-US"), "11/30/2026");
});
