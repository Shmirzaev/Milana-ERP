import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import ts from "typescript";

const root = path.resolve(import.meta.dirname, "..");
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
assert.equal(scriptDirective, "script-src 'self' 'nonce-nonce_A1'");
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
