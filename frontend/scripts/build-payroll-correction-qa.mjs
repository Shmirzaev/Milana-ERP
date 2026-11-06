// Static bundle of the real QR Control page; all payroll/auth requests use the
// disposable FastAPI instance. This compiler starts no frontend server.
import { build } from "esbuild";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { execFileSync } from "node:child_process";

const root = process.cwd();
const output = process.env.LABEL_CORRECTION_QA_OUTPUT;
if (!output) throw new Error("LABEL_CORRECTION_QA_OUTPUT is required");
await mkdir(output, { recursive: true });
await build({
  stdin: { resolveDir: root, loader: "tsx", contents: `
    import React from 'react';
    import {createRoot} from 'react-dom/client';
    import Page from './src/app/(app)/payroll/qr-control/page';
    import {LangProvider} from './src/lib/i18n';
    import {DialogProvider} from './src/components/DialogProvider';
    localStorage.setItem('erp_lang', new URLSearchParams(location.search).get('lang') || 'en');
    createRoot(document.getElementById('root')).render(<LangProvider><DialogProvider><Page/></DialogProvider></LangProvider>);
  ` },
  tsconfig: resolve(root, "tsconfig.json"), bundle: true,
  outfile: resolve(output, "payroll-app.js"), format: "iife", jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
});
execFileSync(process.execPath, [resolve(root, "node_modules/tailwindcss/lib/cli.js"),
  "-i", "src/app/globals.css", "-o", resolve(output, "payroll-app.css"), "--minify"], { cwd: root, stdio: "pipe" });
await writeFile(resolve(output, "payroll-app.html"), `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Disposable payroll correction QA</title><link rel="stylesheet" href="/qa-assets/payroll-app.css"></head><body><main id="root" class="p-4"></main><script src="/qa-assets/payroll-app.js"></script></body></html>`);
console.log(`Actual QR Control page bundled with real API/auth; output ${output}`);
