import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

// Exercise the real component/helpers/translations without starting an app or
// touching a database. Connected-browser selection/preview checks are separate.
const root = path.resolve(import.meta.dirname, "..");
const require = createRequire(import.meta.url);
let language = "en";
const cache = new Map();
function compile(source, filename) {
  return ts.transpileModule(source, { fileName: filename, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText;
}
function load(filename) {
  if (cache.has(filename)) return cache.get(filename);
  const exports = {};
  cache.set(filename, exports);
  new Function("exports", "require", compile(fs.readFileSync(filename, "utf8"), filename))(exports, (name) => {
    if (name === "@/lib/i18n") return { useT: () => ({ t: key => messages[language][key] ?? key }) };
    if (!name.startsWith("@/") && !name.startsWith(".")) return require(name);
    const base = name.startsWith("@/") ? path.join(root, "src", name.slice(2)) : path.resolve(path.dirname(filename), name);
    const resolved = [base, `${base}.ts`, `${base}.tsx`].find(file => fs.existsSync(file) && fs.statSync(file).isFile());
    assert.ok(resolved, `Missing dependency ${name}`);
    return load(resolved);
  });
  return exports;
}
const messages = Object.fromEntries(["en", "ru", "uz"].map(lang => [lang, {
  ...load(path.join(root, `src/lib/i18n/locales/${lang}-base.ts`)).default,
  ...load(path.join(root, `src/lib/i18n/locales/${lang}-supplemental.ts`)).default,
}]));
const Pictures = load(path.join(root, "src/components/ProcessQrModelPictures.tsx")).default;
const model = { id: 41, code: "MODEL-41", primary_image_url: "/storage/model-files/model41.png", variant_picture_url: "/storage/model-files/variant41.png" };
let cases = 0;
function check(name, fn) { fn(); cases++; console.log(`PASS ${name}`); }
function render(value = model) { return renderToStaticMarkup(React.createElement(Pictures, { model: value })); }
const decode = text => text.replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/&quot;/g, '"');
for (const [lang, labels] of Object.entries({
  en: ["Model variant", "Model", "Variant", "No image"],
  ru: ["Вариант модели", "Модель", "Вариант", "Нет фото"],
  uz: ["Model varianti", "Model", "Variant", "Rasm yo'q"],
})) {
  language = lang;
  check(`${lang} two labeled uncropped thumbnails and full-image preview links`, () => {
    const html = decode(render());
    assert.ok(html.includes(`aria-label="${labels[0]}"`));
    for (const label of labels.slice(1, 3)) assert.ok(html.includes(`>${label}</figcaption>`));
    assert.equal((html.match(/<figure/g) ?? []).length, 2);
    assert.equal((html.match(/object-contain/g) ?? []).length, 2);
    const srcs = [...html.matchAll(/<img[^>]+src="([^"]+)"/g)].map(m => m[1]);
    assert.deepEqual(srcs, ["/storage/model-files/thumb/model41.png?size=160&quality=hq3", "/storage/model-files/thumb/variant41.png?size=160&quality=hq3"]);
    const urls = [...html.matchAll(/<a[^>]+href="([^"]+)"/g)].map(m => new URL(m[1], "http://qa.invalid"));
    assert.deepEqual(urls.map(url => url.pathname), ["/image-preview", "/image-preview"]);
    assert.deepEqual(urls.map(url => url.searchParams.get("src")), ["/storage/model-files/model41.png", "/storage/model-files/variant41.png"]);
    assert.ok(urls[0].searchParams.get("title").startsWith(`${labels[1]}: `));
    assert.ok(urls[1].searchParams.get("title").startsWith(`${labels[2]}: `));
    assert.equal((html.match(/rel="noopener noreferrer"/g) ?? []).length, 2);
  });
  check(`${lang} absent model has two readable placeholders and no links/images`, () => {
    const html = decode(renderToStaticMarkup(React.createElement(Pictures)));
    assert.ok(html.includes(`${labels[1]}: ${labels[3]}`));
    assert.ok(html.includes(`${labels[2]}: ${labels[3]}`));
    assert.equal((html.match(/<a\s/g) ?? []).length, 0);
    assert.equal((html.match(/<img\s/g) ?? []).length, 0);
    assert.equal((html.match(/<figure/g) ?? []).length, 2);
  });
}
language = "en";
check("one missing variant does not hide the model image or invent a preview", () => {
  const html = render({ ...model, variant_picture_url: null });
  assert.equal((html.match(/<img\s/g) ?? []).length, 1);
  assert.equal((html.match(/<a\s/g) ?? []).length, 1);
  assert.ok(html.includes("Variant: No image"));
});
check("existing thumbnail input links to its full original", () => {
  const html = decode(render({ ...model, primary_image_url: "/storage/model-files/thumb/full.png?size=320&quality=hq3" }));
  const firstHref = new URL(html.match(/<a[^>]+href="([^"]+)"/)[1], "http://qa.invalid");
  assert.equal(firstHref.searchParams.get("src"), "/storage/model-files/full.png");
  assert.ok(html.includes('src="/storage/model-files/thumb/full.png?size=320&quality=hq3"'));
});

// Evaluate the exact JSX expression used by the real page. These tests detect
// stale SWR model exposure and loss of the selection key, not only source tokens.
const pagePath = path.join(root, "src/app/(app)/process-qr/page.tsx");
const pageSource = fs.readFileSync(pagePath, "utf8");
const ast = ts.createSourceFile(pagePath, pageSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const expressions = [];
function walk(node) {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === "ProcessQrModelPictures") {
    let parent = node.parent;
    while (parent && !ts.isJsxExpression(parent)) parent = parent.parent;
    assert.ok(parent?.expression);
    expressions.push(parent.expression.getText(ast));
  }
  ts.forEachChild(node, walk);
}
walk(ast);
assert.equal(expressions.length, 1);
const compiled = compile(`export function pick(selectedModelId, selectedModel) { return (${expressions[0]}); }`, "selection.tsx");
const output = {};
new Function("exports", "require", "ProcessQrModelPictures", compiled)(output, require, Pictures);
const pick = output.pick;
check("selected model renders with the selection identity as key", () => {
  const result = pick(41, model);
  assert.equal(result.key, "41");
  assert.equal(result.props.model, model);
});
check("switching selection rejects stale prior-model data until new response arrives", () => {
  const result = pick(42, model);
  assert.equal(result.key, "42");
  assert.equal(result.props.model, undefined);
  assert.equal((renderToStaticMarkup(result).match(/<img\s/g) ?? []).length, 0);
  const next = { ...model, id: 42, primary_image_url: "/storage/model-files/model42.png", variant_picture_url: null };
  assert.equal(pick(42, next).props.model, next);
  assert.notEqual(pick(42, next).key, pick(41, model).key);
});
check("no selection does not expose the stale cached model", () => {
  assert.ok(!pick(null, model));
  assert.ok(!pick(undefined, model));
  assert.ok(!pick(0, model));
});
check("mismatched identity types do not bypass the strict selected-model check", () => {
  assert.equal(pick(41, { ...model, id: "41" }).props.model, undefined);
});
console.log(`Process QR model pictures: ${cases} runtime cases passed; browser verification remains separate.`);
