import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const compile = (source, deps) => {
  const code = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const exports = {};
  new Function("exports", "require", code)(exports, name => {
    assert.ok(name in deps, `unexpected dependency ${name}`);
    return deps[name];
  });
  return exports;
};
const errors = compile(fs.readFileSync(new URL("../src/lib/errorMessages.ts", import.meta.url), "utf8"), {});
const source = fs.readFileSync(new URL("../src/app/(app)/brands/page.tsx", import.meta.url), "utf8");
const element = (type, props) => ({ type, props: props || {} });
function walk(node, out = []) {
  if (Array.isArray(node)) node.forEach(child => walk(child, out));
  else if (node && typeof node === "object") { out.push(node); walk(node.props?.children, out); }
  return out;
}
function harness() {
  const state = [], refs = [], calls = [];
  let cursor = 0, failure = null, reloads = 0, pending = null;
  const deps = {
    react: { useState(initial) {
      const i = cursor++;
      if (!(i in state)) state[i] = initial;
      return [state[i], value => { state[i] = typeof value === "function" ? value(state[i]) : value; }];
    }, useRef(initial) {
      const i = cursor++;
      if (!(i in refs)) refs[i] = { current: initial };
      return refs[i];
    }, useMemo: fn => fn() },
    "react/jsx-runtime": { jsx: element, jsxs: element, Fragment: "fragment" },
    "next/navigation": { useSearchParams: () => ({ get: () => null }) },
    swr: { default: () => ({ data: [], mutate: () => { reloads++; } }) },
    "@/lib/api": { api: { post: async (...args) => { calls.push(structuredClone(args)); if (pending) await pending; if (failure) throw failure; } }, fetcher() {} },
    "@/lib/errorMessages": errors,
    "@/components/PageHeader": { default: "header" },
    "@/components/Modal": { default: "modal" },
    "@/lib/auth": { useMe: () => ({ me: {} }), can: () => false },
    "@/lib/i18n": { useT: () => ({ t: key => key }) },
  };
  const Page = compile(source, deps).default;
  const render = () => { cursor = 0; return walk(Page()); };
  const form = () => render().find(node => node.type === "form");
  const inputs = () => render().filter(node => node.type === "input" && node.props.placeholder);
  const alert = () => render().find(node => node.props?.role === "alert");
  return { render, form, inputs, alert, calls, reloads: () => reloads, fail: value => { failure = value; }, delay: value => { pending = value; } };
}

test("refusal preserves fields, announces localized error and retry sends one request", async () => {
  for (const lang of ["en", "ru", "uz"]) {
    globalThis.document = { documentElement: { lang } };
    const h = harness();
    h.inputs()[0].props.onChange({ target: { value: "Existing" } });
    h.inputs()[1].props.onChange({ target: { value: "kept" } });
    h.fail(new errors.ApiError(409, "Brand already exists"));
    await h.form().props.onSubmit({ preventDefault() {} });
    assert.equal(h.calls.length, 1);
    assert.deepEqual(h.calls[0], ["/api/brands", { name: "Existing", description: "kept" }]);
    assert.equal(h.inputs()[0].props.value, "Existing");
    assert.equal(h.inputs()[1].props.value, "kept");
    assert.equal(h.alert().props.children, new errors.ApiError(409, "Brand already exists").message);
    const expected = { en: "Brand already exists", ru: "Этот бренд уже существует.", uz: "Bu brend allaqachon mavjud." };
    assert.equal(errors.localizeError("Brand already exists", 409, lang), expected[lang]);
    assert.equal(h.reloads(), 0);
    h.fail(null);
    await h.form().props.onSubmit({ preventDefault() {} });
    assert.equal(h.calls.length, 2);
    assert.equal(h.alert(), undefined);
    assert.equal(h.inputs()[0].props.value, "");
    assert.equal(h.inputs()[1].props.value, "");
    assert.equal(h.reloads(), 1);
  }
});

test("network failure keeps input and does not retry or refresh", async () => {
  globalThis.document = { documentElement: { lang: "en" } };
  const h = harness();
  h.inputs()[0].props.onChange({ target: { value: "Preserve" } });
  h.fail(new errors.ApiError(0, "Failed to fetch"));
  await h.form().props.onSubmit({ preventDefault() {} });
  assert.equal(h.calls.length, 1);
  assert.equal(h.inputs()[0].props.value, "Preserve");
  assert.match(h.alert().props.children, /Failed to fetch/);
  assert.equal(h.reloads(), 0);
});


test("rapid submissions are blocked synchronously while the request is pending", async () => {
  globalThis.document = { documentElement: { lang: "en" } };
  const h = harness();
  let resolve;
  h.delay(new Promise(done => { resolve = done; }));
  h.inputs()[0].props.onChange({ target: { value: "Single" } });
  const submit = h.form().props.onSubmit;
  const first = submit({ preventDefault() {} });
  await submit({ preventDefault() {} });
  assert.equal(h.calls.length, 1);
  assert.ok(h.inputs().every(input => input.props.disabled === true));
  assert.equal(h.render().find(node => node.type === "button" && node.props.children === "btn.create").props.disabled, true);
  resolve();
  await first;
  assert.equal(h.calls.length, 1);
  assert.equal(h.reloads(), 1);
  assert.ok(h.inputs().every(input => input.props.disabled === false));
  assert.equal(h.render().find(node => node.type === "button" && node.props.children === "btn.create").props.disabled, false);
});
