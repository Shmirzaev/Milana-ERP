import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import ts from "typescript";

function load(path, dependencies = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpile(fs.readFileSync(path, "utf8"), {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  }), { exports, require: (name) => dependencies[name] || {} });
  return exports;
}

const enums = load("src/lib/brandedPlanning.ts");
const backend = fs.readFileSync("../backend/app/libs/enums/planning.py", "utf8");
const expected = {
  BrandedPlanningOrderType: ["customer", "milana", "eco_cotton", "besttex"],
  BrandedPlanningOrderStatus: ["open", "closed", "cancelled"],
  BrandedCuttingProgress: ["not_started", "partial", "completed"],
};
for (const [name, values] of Object.entries(expected)) {
  assert.deepEqual(Object.values(enums[name]), values, `${name}: frontend vocabulary`);
  const body = backend.split(`class ${name}(str, Enum):`)[1]?.split(/\nclass /)[0];
  assert(body, `${name}: missing backend declaration`);
  const persisted = Array.from(body.matchAll(/^\s+[A-Z_]+ = "([^"]+)"/gm), (match) => match[1]);
  assert.deepEqual(persisted, values, `${name}: backend/frontend parity`);
}

// Exercise the actual component's render branches, with deterministic hooks.
// Browser verification remains a separate gate.
const jsx = (type, props) => ({ type, props });
const History = load("src/components/BrandedOrderHistory.tsx", {
  "react/jsx-runtime": { jsx, jsxs: jsx },
  react: { useMemo: (fn) => fn(), useState: (value) => [value, () => {}] },
  "@/lib/brandedPlanning": enums,
  "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
  "@/lib/orderRef": { formatOrderReference: (value) => value },
  "@/lib/modelCode": { normalizeModelSearch: (value) => value || "" },
  "@/components/StagePipeline": { statusLabel: (value) => `production:${value}` },
}).default;
function descendants(node) {
  if (Array.isArray(node)) return node.flatMap(descendants);
  if (!node || typeof node !== "object") return [];
  return [node, ...descendants(node.props?.children)];
}
for (const [progress, color] of [[undefined, "white"], ["not_started", "white"], ["partial", "yellow-100"], ["completed", "green-100"]]) {
  const nodes = descendants(History({
    orders: [{ id: 7, order_no: "BR-7", ordered_for_type: "milana", ordered_for_name: "Milana",
      status: "open", created_at: "2026-10-26", production_count: 1, total_quantity: 12,
      cutting_status: progress,
      productions: [{ id: 9, order_no: "PO-9", production_no: "PO-9", model_id: 1,
        planned_quantity: 12, status: "in_progress", cutting_status: progress }],
    }], models: [], activeOrderId: 7, creating: false, error: "", onNewOrder() {}, onAddProduction() {},
  }));
  assert(nodes.find((node) => node.type === "summary").props.className.includes(`bg-${color}`));
  assert(nodes.find((node) => node.type === "tr" && node.props.className).props.className.includes(`bg-${color}`));
  assert(nodes.some((node) => node.props.children === `page.planning.cutting.${progress || "not_started"}`));
  assert(nodes.some((node) => node.props.children === "production:in_progress"));
}
console.log("Planning enum parity and history rendering passed (4 progress/fallback cases).");
