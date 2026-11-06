import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = fs.readFileSync("src/app/(app)/cutting-passports/page.tsx", "utf8");
const ast = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const computeNode = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === "compute");
assert.ok(computeNode);
const code = ts.transpileModule(computeNode.getText(ast), {
  compilerOptions: { target: ts.ScriptTarget.ES2020 },
}).outputText;
const context = vm.createContext({});
vm.runInContext(code, context);
const form = {
  meter_mode: true, pieces: 315, beka_per_piece_kg: 0.1, other_beka_per_piece_kg: 0,
  ribana_per_piece_kg: 0, scrap_kg: 0, layer_weight_kg: 7.85, total_layers: 63,
  planned_kg: 495, fabric_width_m: 1.72, lay_length_m: 7.88, gramage: 0.191,
};
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 0.000001, `${actual} != ${expected}`);
const screenshot = context.compute(form, 5);
near(screenshot.AE, 1.676);
near(screenshot.Q, 527.94);
near(screenshot.P, 526.05);
near(screenshot.AF, 1.67);
near(screenshot.X, 31.5);
const bothBindings = context.compute({ ...form, other_beka_per_piece_kg: 0.015, scrap_kg: 2 }, 5);
near(bothBindings.AE, 1.691);
near(bothBindings.Q, 534.665);
const zeroBinding = context.compute({ ...form, beka_per_piece_kg: 0 }, 5);
near(zeroBinding.AE, 1.576);
near(zeroBinding.Q, 496.44);
near(context.compute({ ...form, fabric_width_m: 0, gramage: 0 }, 5).AE, 1.676);
near(context.compute(form, 0).AE, 0);
near(context.compute(form, 0).Q, 0);
near(context.compute({ ...form, pieces: 0 }, 5).Q, 0);
const kg = context.compute({ ...form, meter_mode: false }, 5);
near(kg.AE, 1.72 * 7.88 * 0.191 / 5 + 0.1);
near(kg.Q, kg.AE * 315);
console.log("Meter binding is included per piece exactly once; totals, other binding, zero cases and kg mode pass.");
