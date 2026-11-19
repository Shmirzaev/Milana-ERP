import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const root = path.resolve(import.meta.dirname, "..");
const require = createRequire(import.meta.url);
const cache = new Map();
let language = "en";
let failedSrc = null;
let bandRows = [];
function compile(source, filename) {
  return ts.transpileModule(source, { fileName: filename, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
}
function load(filename) {
  if (cache.has(filename)) return cache.get(filename);
  const exports = {};
  cache.set(filename, exports);
  new Function("exports", "require", compile(fs.readFileSync(filename, "utf8"), filename))(exports, name => {
    // Node does not compile CSS modules; the actual application build verifies
    // their styles. Keep rendering the real component and its image bindings.
    if (name.endsWith(".module.css")) return { default: new Proxy({}, { get: (_, key) => String(key) }) };
    if (name === "react" && filename.endsWith("ImageThumbnail.tsx")) return {
      ...React, useState: () => [failedSrc, value => { failedSrc = value; }],
    };
    if (name === "next/link") return { default: ({ children, ...props }) => React.createElement("a", props, children) };
    if (name === "@/lib/auth") return { useMe: () => ({ me: { name: "Band", sewing_band_id: 54 } }), can: () => false };
    if (name === "@/lib/i18n") return { useT: () => ({ t }) };
    if (name === "@/components/StagePipeline") return { operationLabel: value => value, statusLabel: value => value };
    if (name === "@/components/PageHeader") return { default: () => null };
    if (name === "@/lib/api") return { fetcher() {} };
    if (name === "swr") return { default: key => {
      assert.equal(key, "/api/sewing-bands/orders");
      return { data: bandRows };
    } };
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
function t(key, vars = {}) {
  return Object.entries(vars).reduce((result, [name, value]) => result.replaceAll(`{${name}}`, value), messages[language][key] ?? key);
}
const DepartmentList = load(path.join(root, "src/components/DepartmentOrderList.tsx")).default;
const CuttingList = load(path.join(root, "src/components/CuttingOrderList.tsx")).default;
const BandFloor = load(path.join(root, "src/components/sewing/BandFloor.tsx")).default;
const Thumbnail = load(path.join(root, "src/components/ImageThumbnail.tsx")).default;
const row = {
  id: 8, work_order_id: 8, production_order_id: 11, order_no: "ORDER-11", model_no: "MODEL-1", operation: "sewing",
  model_image_url: "/storage/model-files/garment.png", material_image_url: "/storage/model-files/variant.png",
  print_image_url: "/storage/sales-order-files/art.png?exp=1900000000&sig=retained",
};
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const decode = text => text.replace(/&amp;/g, "&").replace(/&#x27;/g, "'").replace(/&quot;/g, '"');
function assertPictures(html, label) {
  html = decode(html);
  const sources = [...html.matchAll(/<img[^>]+src="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(sources, ["/storage/model-files/thumb/garment.png?size=160&quality=hq3", "/storage/model-files/thumb/variant.png?size=160&quality=hq3", row.print_image_url]);
  assert.ok(html.includes(`<th>${label}</th>`) || html.includes(`>${label}</th>`));
  assert.equal((html.match(/object-contain/g) ?? []).length, 1, "artwork fits the whole image");
  const hrefs = [...html.matchAll(/<a[^>]+href="([^"]+)"/g)].map(match => new URL(match[1], "http://qa.invalid"));
  const artwork = hrefs.find(url => url.pathname === "/image-preview" && url.searchParams.get("src") === row.print_image_url);
  assert.ok(artwork, "preview preserves the signed artwork URL");
}
let cases = 0;
for (const [lang, label] of Object.entries({ en: "Print picture", ru: "Изображение принта", uz: "Print rasmi" })) {
  language = lang;
  assertPictures(render(DepartmentList, { rows: [row], title: "Orders", emptyLabel: "Empty", t }), label);
  assertPictures(render(CuttingList, { rows: [row], cuttingDepartment: "CUT", t }), label);
  bandRows = [{ ...row, sewing_assignment_id: 4 }];
  assertPictures(render(BandFloor), label);
  const absent = decode(render(DepartmentList, { rows: [{ ...row, print_image_url: null }], title: "Orders", emptyLabel: "Empty", t }));
  assert.equal((absent.match(/<img\s/g) ?? []).length, 2, "missing artwork retains garment and material images");
  assert.ok(absent.includes(`${label}: ${t("page.workOrder.noImage")}`));
  cases += 4;
}
language = "en";
// Exercise the real thumbnail's error handler and subsequent render. A failed
// image loses its broken preview link; a newly supplied URL can load normally.
const thumbProps = { imageUrl: row.print_image_url, label: "Artwork", title: "Print picture", emptyLabel: "No image", fit: "contain" };
const initial = Thumbnail(thumbProps);
initial.props.children.props.onError();
const failed = Thumbnail(thumbProps);
assert.equal(failed.type, "div");
assert.equal(failed.props["aria-label"], "Print picture: No image");
assert.ok(failed.props.children, "failed image retains the placeholder icon");
const recovered = Thumbnail({ ...thumbProps, imageUrl: `${row.print_image_url}-fresh` });
assert.equal(recovered.props.children.type, "img");
assert.equal(recovered.props.children.props.className, "h-full w-full object-contain");
failedSrc = null;
cases++;

// The partial-packaging table is separate from DepartmentOrderList: render its
// actual JSX expression, so a wrong field binding fails this check too.
const pagePath = path.join(root, "src/app/(app)/departments/[code]/page.tsx");
const pageSource = fs.readFileSync(pagePath, "utf8");
const ast = ts.createSourceFile(pagePath, pageSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const artworkExpressions = [];
function walk(node) {
  if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(ast) === "ImageThumbnail"
      && node.attributes.properties.some(prop => prop.name?.getText(ast) === "imageUrl" && prop.initializer?.getText(ast) === "{r.print_image_url}")) {
    artworkExpressions.push(node.getText(ast));
  }
  ts.forEachChild(node, walk);
}
walk(ast);
assert.equal(artworkExpressions.length, 1);
const output = {};
new Function("exports", "require", "ImageThumbnail", compile(`export function artwork(r, t) { return (${artworkExpressions[0]}); }`, "packaging.tsx"))(output, require, Thumbnail);
const markup = decode(renderToStaticMarkup(output.artwork(row, t)));
assert.ok(markup.includes(`src="${row.print_image_url}"`));
assert.ok(markup.includes("object-contain"));
cases++;
console.log(`PASS: ${cases} rendered floor-artwork, language, signed-preview, absence and failed-image cases.`);
