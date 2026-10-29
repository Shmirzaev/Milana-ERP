import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const ts = process.env.MILANA_NODE_MODULES
  ? require(path.join(process.env.MILANA_NODE_MODULES, "typescript"))
  : require("typescript");
const source = process.env.MODEL_BOM_PAGE
  ? fs.readFileSync(process.env.MODEL_BOM_PAGE, "utf8")
  : fs.readFileSync(new URL("../src/app/(app)/models/[id]/page.tsx", import.meta.url), "utf8");
const element = (type, props) => ({ type, props: props || {} });
function walk(node, out = []) {
  if (Array.isArray(node)) node.forEach(child => walk(child, out));
  else if (node && typeof node === "object") {
    out.push(node);
    walk(node.props?.children, out);
  }
  return out;
}
function compile(source, deps) {
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("exports", "require", code)(exports, name => {
    assert.ok(name in deps, "Unexpected dependency: " + name);
    return deps[name];
  });
  return exports;
}
const errors = compile(fs.readFileSync(new URL("../src/lib/errorMessages.ts", import.meta.url), "utf8"), {});

function harness(scope) {
  const values = [], calls = [], notices = [];
  let cursor = 0, nodes = [], failure = null, revalidations = 0;
  const model = { id: 7, code: "TEST", name: "Synthetic", status: "draft", bom: [],
    images: [], sizes: [], colors: [], details_json: {} };
  const items = [{ id: 11, name: "Fabric", category: "fabric", unit: "kg", is_active: true },
    { id: 12, name: "Accessory", category: "accessory", unit: "pcs", is_active: true }];
  const root = scope === "usluga" ? "/api/usluga/models" : "/api/models";
  const refresh = async () => { revalidations++; };
  const apiWrite = async (method, url, payload) => {
    calls.push({ method, url, payload: structuredClone(payload) });
    if (failure) throw new Error(failure);
    if (method === "post") model.bom.push({ ...payload, id: model.bom.length + 1 });
    else {
      const row = model.bom.find(row => url.endsWith("/" + row.id));
      assert.ok(row); Object.assign(row, payload);
    }
    return { id: model.bom.length };
  };
  const deps = {
    react: { useState(initial) {
      const index = cursor++;
      if (!(index in values)) values[index] = typeof initial === "function" ? initial() : initial;
      return [values[index], next => { values[index] = typeof next === "function" ? next(values[index]) : next; }];
    }, useMemo: fn => fn(), useEffect() {} },
    "react/jsx-runtime": { jsx: element, jsxs: element, Fragment: "fragment" },
    "next/link": { default: "link" },
    "next/navigation": { useParams: () => ({ id: "7" }), usePathname: () => scope === "usluga" ? "/usluga/models/7" : "/models/7",
      useRouter: () => ({ push() {} }), useSearchParams: () => ({ get: () => "edit" }) },
    swr: { default: key => ({ data: key === root + "/7" ? model : key?.endsWith("/bom-items") ? items : [], mutate: refresh }) },
    "swr/infinite": { default: () => ({ data: [[]], mutate: refresh, size: 1, setSize() {} }) },
    "lucide-react": { Edit3: "icon", Plus: "icon", Trash2: "icon" },
    "@/lib/api": { api: { post: (...a) => apiWrite("post", ...a), patch: (...a) => apiWrite("patch", ...a) }, fetcher() {} },
    "@/lib/i18n": { useT: () => ({ lang: "en", t: key => key }) },
    "@/components/DialogProvider": { useDialogs: () => ({ notify: async message => notices.push(message), ask: async () => true }) },
    "@/components/SearchableSelect": { default: "search-select" },
    "@/components/PageHeader": { default: "header" },
    "@/components/StagePipeline": { statusLabel: value => value },
    "@/lib/auth": { useMe: () => ({ me: { permissions: ["*"], role: "admin" } }) },
    "@/lib/errorMessages": errors,
    "@/lib/modelBom": { BOM_MATERIAL_ROLE_MAIN: "main", BOM_MATERIAL_ROLE_SECONDARY: "secondary" },
    "@/lib/variantDisplay": { formatVariantNumber: value => value },
    "@/lib/modelCode": { buildModelCode: () => "", modelCodeParts: () => ({ modelNo: "", variantNo: "" }) },
    "@/lib/materialComposition": { compositionTotal: () => 0, formatComposition: () => "" },
    "@/lib/modelComposition": { formatModelComposition: () => "" },
    "@/lib/oldErpModelInfo": { oldErpModelInfoFromDetails: () => ({ recipes: [] }) },
    "@/lib/modelImages": { imagePreviewHref: x => x, storageThumbnailUrl: x => x },
    "@/lib/imageUpload": { prepareModelImageUpload: async x => x },
    "@/lib/garmentSizes": { GARMENT_SIZE_OPTIONS: [], garmentSizeRange: () => [], garmentSizeRangeEndOptions: () => [] },
    "@/lib/numberInput": { parseNumberInput: x => Number(x) },
    "@/components/VerticalModelPhoto": { default: "photo" },
    "@/components/VariantColorSelect": { default: "color-select" },
    "@/components/PaidOperationsEditor": { default: "paid-operations" },
    "@/lib/modelPaidOperations": { createPaidOperation: () => ({}), materializeLegacyPaidOperations: () => [],
      PAID_OPERATION_FACTORIES: [], paidOperationFactoryFromDepartmentCode: () => undefined,
      paidOperationsFromDetails: () => [], serializePaidOperations: () => [], samePaidProcess: () => false,
      withPaidOperations: x => x },
  };
  const Page = compile(source, deps).default;
  function render() { cursor = 0; nodes = walk(Page()); return nodes; }
  function text(node) {
    if (typeof node === "string" || typeof node === "number") return String(node);
    if (Array.isArray(node)) return node.map(text).join("");
    return node && typeof node === "object" ? text(node.props?.children) : "";
  }
  function button(label) { return nodes.find(n => n.type === "button" && text(n).includes(label)); }
  function field(placeholder) { return nodes.find(n => n.type === "input" && n.props.placeholder === placeholder); }
  function form(section) {
    const marker = section === "material" ? "page.modelDetail.qtyPerPieceShort" : "page.modelDetail.qtyPerPieceShort";
    const forms = nodes.filter(n => n.type === "form" && walk(n).some(x => x.props?.placeholder === marker));
    assert.equal(forms.length, 2);
    return forms[section === "material" ? 0 : 1];
  }
  function open() {
    render(); const tab = button("page.modelDetail.tab.materials"); assert.ok(tab); tab.props.onClick(); render();
  }
  function setMaterial(name) {
    if (scope === "usluga") field("page.modelDetail.manualFabricName").props.onChange({ target: { value: name } });
    else {
      const select = walk(form("material")).find(n => n.type === "search-select");
      assert.ok(select); select.props.onChange(11);
    }
    render();
  }
  function setAccessory() {
    const select = walk(form("accessory")).find(n => n.type === "search-select");
    assert.ok(select); select.props.onChange(12); render();
  }
  async function submit(section) {
    await form(section).props.onSubmit({ preventDefault() {} }); render();
  }
  function editFirst(section) {
    const edit = nodes.find(n => n.type === "button" && n.props.title === "btn.edit");
    assert.ok(edit); edit.props.onClick(); render();
  }
  function selection(section) { return walk(form(section)).find(n => n.type === "search-select")?.props.value; }
  return { open, render, setMaterial, setAccessory, submit, editFirst, button, field, selection, model, calls, notices,
    fail: message => { failure = message; }, text: () => nodes.map(text).join(" "),
    get visibleRows() { return nodes.filter(n => n.type === "button" && n.props.title === "btn.edit").length; },
    get revalidations() { return revalidations; } };
}

for (const scope of ["standard", "usluga"]) {
  test(scope + ": success then refused add clears success and retains entered form without phantom row", async () => {
    const ui = harness(scope); ui.open(); ui.setMaterial("First fabric"); await ui.submit("material");
    assert.match(ui.text(), /page.modelDetail.msg.addedToFabrics/);
    assert.equal(ui.model.bom.length, 1);
    assert.equal(ui.visibleRows, 1);
    ui.setMaterial("Second fabric"); ui.fail("409: duplicate main fabric");
    const beforeRefresh = ui.revalidations;
    await ui.submit("material");
    assert.equal(ui.notices.at(-1), "409: duplicate main fabric");
    assert.doesNotMatch(ui.text(), /page.modelDetail.msg.addedToFabrics/);
    assert.equal(ui.model.bom.length, 1);
    assert.equal(ui.visibleRows, 1);
    assert.equal(ui.revalidations, beforeRefresh);
    if (scope === "usluga") assert.equal(ui.field("page.modelDetail.manualFabricName").props.value, "Second fabric");
    else assert.equal(ui.selection("material"), 11);
    assert.equal(ui.calls.at(-1).url, scope === "usluga" ? "/api/usluga/models/7/bom" : "/api/models/7/bom");
  });

  test(scope + ": accessory add and material edit retain success behavior and report failed edit", async () => {
    const ui = harness(scope); ui.open(); ui.setMaterial("Initial fabric"); await ui.submit("material");
    ui.editFirst("material"); ui.fail("409: edit refused"); await ui.submit("material");
    assert.equal(ui.notices.at(-1), "409: edit refused");
    assert.equal(ui.model.bom.length, 1);
    assert.equal(ui.visibleRows, 1);
    assert.doesNotMatch(ui.text(), /page.modelDetail.msg.addedToFabrics/);
    if (scope === "usluga") assert.equal(ui.field("page.modelDetail.manualFabricName").props.value, "Initial fabric");
    else assert.equal(ui.selection("material"), 11);
    ui.fail(null); await ui.submit("material");
    assert.equal(ui.calls.at(-1).method, "patch");
    assert.match(ui.text(), /page.modelDetail.msg.updatedBom/);
    ui.setAccessory(); ui.fail("409: accessory refused"); await ui.submit("accessory");
    assert.equal(ui.notices.at(-1), "409: accessory refused");
    assert.equal(ui.selection("accessory"), 12);
    assert.equal(ui.model.bom.length, 1);
    assert.doesNotMatch(ui.text(), /page.modelDetail.msg.updatedBom/);
    ui.fail(null); await ui.submit("accessory");
    assert.equal(ui.calls.at(-1).payload.item_id, 12);
    assert.match(ui.text(), /page.modelDetail.msg.addedToAccessories/);
    assert.equal(ui.model.bom.length, 2);
    assert.equal(ui.visibleRows, 2);
  });
}
