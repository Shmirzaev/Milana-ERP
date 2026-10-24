import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import ts from "typescript";

const root = path.resolve(import.meta.dirname, "..");
// Assert the current production headers before loading newly introduced helpers.
const baselineRequire = createRequire(import.meta.url);
const savedNodeEnv = process.env.NODE_ENV;
const savedApi = process.env.API_URL;
process.env.NODE_ENV = "production";
process.env.API_URL = "https://api.example.test";
try {
  const rules = await baselineRequire("../next.config.js").headers();
  const globalHeaders = rules.find(rule => rule.source === "/:path*").headers;
  assert.equal(globalHeaders.find(header => header.key === "Strict-Transport-Security")?.value, "max-age=31536000; includeSubDomains");
  assert.equal(globalHeaders.some(header => header.key === "Content-Security-Policy" && /script-src[^;]*'unsafe-inline'/.test(header.value)), false);
} finally {
  if (savedNodeEnv === undefined) delete process.env.NODE_ENV;
  else process.env.NODE_ENV = savedNodeEnv;
  if (savedApi === undefined) delete process.env.API_URL;
  else process.env.API_URL = savedApi;
  delete baselineRequire.cache[baselineRequire.resolve("../next.config.js")];
}
const source = fs.readFileSync(path.join(root, "src/lib/contentSecurityPolicy.ts"), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const cspModule = { exports: {} };
new Function("module", "exports", "require", "process", compiled)(
  cspModule,
  cspModule.exports,
  createRequire(import.meta.url),
  process,
);

const { buildContentSecurityPolicy } = cspModule.exports;
const productionPolicy = buildContentSecurityPolicy("nonce_A1", {
  development: false,
  connectOrigins: ["https://api.example.test/path", "https://api.example.test/other", "not-a-url"],
});
const scriptDirective = productionPolicy.split("; ").find((value) => value.startsWith("script-src "));
const printScript = 'document.getElementById("print-labels").addEventListener("click", function () { window.print(); });';
const cspHash = value => `sha256-${createHash("sha256").update(value).digest("base64")}`;
assert.equal(scriptDirective, `script-src 'self' 'nonce-nonce_A1' '${cspHash(printScript)}'`);
assert.ok(productionPolicy.includes(`script-src-attr 'unsafe-hashes' '${cspHash("window.print()")}'`));
assert.ok(!productionPolicy.includes(cspHash("alert(1)")));
// Frontend-only Docker build contexts have no backend directory. Check source
// parity as well when running from the full checkout (including frontend CI).
const backendBundlePath = path.join(root, "../backend/app/api/routes/bundles.py");
if (fs.existsSync(backendBundlePath)) {
  assert.ok(fs.readFileSync(backendBundlePath, "utf8").includes(`_LABEL_PRINT_SCRIPT = '${printScript}'`));
  assert.ok(fs.readFileSync(path.join(root, "../backend/app/services/print_response.py"), "utf8").includes('sha256(b"window.print()")'));
}
assert.ok(!scriptDirective.includes("'unsafe-inline'"));
assert.ok(!scriptDirective.includes("'unsafe-eval'"));
assert.ok(productionPolicy.includes("style-src 'self' 'unsafe-inline'"));
assert.ok(productionPolicy.includes("connect-src 'self' https://api.example.test"));
assert.ok(productionPolicy.includes("upgrade-insecure-requests"));
assert.throws(() => buildContentSecurityPolicy("bad nonce", { development: false }), /URL-safe/);

const developmentPolicy = buildContentSecurityPolicy("development_nonce", { development: true });
assert.ok(developmentPolicy.includes("'unsafe-eval'"));
assert.ok(!developmentPolicy.includes("upgrade-insecure-requests"));

const originalNodeEnv = process.env.NODE_ENV;
const originalPublicApi = process.env.NEXT_PUBLIC_API_URL;
const originalApi = process.env.API_URL;
process.env.NODE_ENV = "production";
process.env.NEXT_PUBLIC_API_URL = "https://api.example.test";
process.env.API_URL = "https://api.example.test";
try {
  const require = createRequire(import.meta.url);
  delete require.cache[require.resolve("../next.config.js")];
  const config = require("../next.config.js");
  const rules = await config.headers();
  const globalHeaders = rules.find((rule) => rule.source === "/:path*").headers;
  assert.equal(
    globalHeaders.find((header) => header.key === "Strict-Transport-Security")?.value,
    "max-age=31536000; includeSubDomains",
  );
  assert.equal(globalHeaders.some((header) => header.key === "Content-Security-Policy"), false);
} finally {
  if (originalNodeEnv === undefined) delete process.env.NODE_ENV;
  else process.env.NODE_ENV = originalNodeEnv;
  if (originalPublicApi === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = originalPublicApi;
  if (originalApi === undefined) delete process.env.API_URL;
  else process.env.API_URL = originalApi;
}

const proxySource = fs.readFileSync(path.join(root, "src/proxy.ts"), "utf8");
const layoutSource = fs.readFileSync(path.join(root, "src/app/layout.tsx"), "utf8");
assert.match(proxySource, /requestHeaders\.set\("Content-Security-Policy", policy\)/);
assert.match(proxySource, /response\.headers\.set\("Content-Security-Policy", policy\)/);
assert.match(proxySource, /requestHeaders\.set\("x-nonce", nonce\)/);
assert.match(layoutSource, /<script nonce=\{nonce\}/);

console.log("security header contracts passed");

// Execute the real proxy with NextRequest/NextResponse, including a forged
// incoming nonce/CSP and router-prefetch headers.
const nextServer = createRequire(import.meta.url)("next/server");
const proxyExports = {};
const proxyCode = ts.transpileModule(proxySource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const requireProxy = name => name === "next/server" ? nextServer : cspModule.exports;
new Function("exports", "require", proxyCode)(proxyExports, requireProxy);
const generated = new Set();
const proxyNodeEnv = process.env.NODE_ENV;
process.env.NODE_ENV = "production";
for (const prefetch of [false, true]) {
  for (let i = 0; i < 2; i++) {
    const request = new nextServer.NextRequest("https://erp.example.test/login", {
      headers: { "x-nonce": "attacker", "Content-Security-Policy": "script-src 'unsafe-inline'", ...(prefetch ? { "next-router-prefetch": "1", purpose: "prefetch" } : {}) },
    });
    const response = proxyExports.proxy(request);
    const nonce = response.headers.get("x-middleware-request-x-nonce");
    const policy = response.headers.get("Content-Security-Policy");
    assert.match(nonce, /^[A-Za-z0-9_-]{32,}$/);
    assert.notEqual(nonce, "attacker");
    assert.equal(generated.has(nonce), false, "fresh nonce per request");
    generated.add(nonce);
    assert.equal(response.headers.get("x-middleware-request-content-security-policy"), policy);
    assert.ok(policy.includes(`'nonce-${nonce}'`));
    assert.ok(!policy.includes("'unsafe-eval'"));
    assert.ok(policy.includes("upgrade-insecure-requests"));
    assert.ok(!policy.includes("'unsafe-inline'", policy.indexOf("script-src")));
  }
}
assert.equal(proxyExports.config.matcher.some(rule => rule.missing?.length), false);
if (proxyNodeEnv === undefined) delete process.env.NODE_ENV;
else process.env.NODE_ENV = proxyNodeEnv;

// Render the async root layout with its actual script bootstrap.
const runtime = await import("react/jsx-runtime");
const layoutExports = {};
const layoutCode = ts.transpileModule(layoutSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText;
const layoutNonce = [...generated][0];
new Function("exports", "require", layoutCode)(layoutExports, name => {
  if (name === "react/jsx-runtime") return runtime;
  if (name === "next/headers") return { headers: async () => new Headers({ "x-nonce": layoutNonce }) };
  if (name === "next/font/google") return { Inter: () => ({ variable: "font" }) };
  if (name === "@/components/Providers") return { default: () => null };
  return {};
});
const rendered = await layoutExports.default({ children: "workspace" });
const head = rendered.props.children.find(child => child.type === "head");
assert.equal(head.props.children.type, "script");
assert.equal(head.props.children.props.nonce, layoutNonce);
assert.match(head.props.children.props.dangerouslySetInnerHTML.__html, /erp_theme/);
console.log("Nonce proxy and layout: fresh nonce, forged header replacement, prefetch and theme bootstrap passed.");
