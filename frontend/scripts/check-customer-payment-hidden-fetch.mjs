import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";

const paymentKey = "/api/customers/8/payments";
const source = fs.readFileSync(new URL("../src/app/(app)/customers/[id]/page.tsx", import.meta.url), "utf8");

assert.match(
  source,
  /const customerPaymentsKey = customer \? `\/api\/customers\/\$\{id\}\/payments` : null;/,
  "payment history must depend on the resolved customer record",
);
assert.match(
  source,
  /if \(!customer\) return <div>\{t\("common\.loading"\)\}<\/div>;/,
  "the unresolved and denied parent render must remain unchanged",
);

const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

function renderCase(customer) {
  const requests = [];
  const jsx = (type, props) => ({ type, props: props || {} });
  const dependencies = {
    "react/jsx-runtime": { jsx, jsxs: jsx, Fragment: "fragment" },
    react: {
      useEffect() {},
      useMemo: (calculate) => calculate(),
      useState: (initial) => [typeof initial === "function" ? initial() : initial, () => {}],
    },
    "next/link": { default: "link" },
    "next/navigation": { useParams: () => ({ id: "8" }) },
    swr: {
      default: (key) => {
        requests.push(key);
        return {
          data: key === "/api/customers/8"
            ? customer
            : key === "/api/customers/8/orders"
              ? []
              : key === paymentKey
                ? [{
                    id: 4,
                    row_key: "payment-4",
                    amount: 25,
                    payment_method: "bank_transfer",
                    paid_at: "2026-09-01T00:00:00Z",
                    notes: null,
                    order_id: null,
                    order_no: null,
                    invoice_id: null,
                    invoice_no: null,
                    is_advance: true,
                  }]
                : undefined,
          mutate() {},
        };
      },
    },
    "lucide-react": { Plus: "plus" },
    "@/lib/api": { api: {}, fetcher() {} },
    "@/components/PageHeader": { default: "page-header" },
    "@/components/Modal": { default: "modal" },
    "@/components/StagePipeline": { statusLabel: (value) => value },
    "@/lib/i18n": { useT: () => ({ t: (key) => key }) },
    "@/lib/numberInput": { numberOrZero: (value) => Number(value || 0), parseNumberInput: (value) => value },
    "@/lib/orderRef": { formatOrderReference: (value) => value },
  };
  const loadedModule = { exports: {} };
  new Function("require", "exports", "module", compiled)((name) => {
    assert.ok(name in dependencies, `Unexpected dependency ${name}`);
    return dependencies[name];
  }, loadedModule.exports, loadedModule);
  const tree = loadedModule.exports.default();
  return { requests: requests.filter(Boolean), tree };
}

function visit(tree, callback) {
  if (tree === null || tree === undefined || typeof tree === "boolean") return;
  if (Array.isArray(tree)) {
    for (const child of tree) visit(child, callback);
    return;
  }
  if (typeof tree !== "object") {
    callback(tree);
    return;
  }
  callback(tree);
  visit(tree.props?.children, callback);
}

function textContent(tree) {
  const values = [];
  visit(tree, (node) => {
    if (typeof node === "string" || typeof node === "number") values.push(String(node));
  });
  return values.join(" ");
}

const active = renderCase({ id: 8, name: "Customer Eight", phone: "", email: "", address: "", notes: "" });
assert.equal(active.requests.filter((key) => key === paymentKey).length, 1);
assert.match(textContent(active.tree), /bank_transfer/);
assert.match(textContent(active.tree), /\$25\.00/);

const deniedOrUnresolved = renderCase(undefined);
assert.equal(deniedOrUnresolved.requests.filter((key) => key === paymentKey).length, 0);
assert.equal(textContent(deniedOrUnresolved.tree), "common.loading");
assert.doesNotMatch(textContent(deniedOrUnresolved.tree), /Customer Eight|bank_transfer|\$25\.00/);

console.log("Customer payment history: denied/unresolved key 1 -> 0; active ledger remains exactly 1.");
