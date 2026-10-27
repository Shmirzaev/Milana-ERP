import { createRequire } from "node:module";
const require=createRequire(import.meta.url);
const {build}=require(process.env.ESBUILD_MODULE_PATH || "esbuild");
import fs from "node:fs";
import path from "node:path";
const root=path.resolve(import.meta.dirname,"../..");
const out=path.join(root,"outputs/preview");
fs.writeFileSync(path.join(out,"sewing-entry.tsx"),"import React from \"react\";\nimport { createRoot } from \"react-dom/client\";\nimport Providers from \"../../frontend/src/components/Providers\";\nimport SewingPage from \"../../frontend/src/app/(app)/work-orders/[id]/sewing/page\";\ncreateRoot(document.getElementById(\"root\")!).render(<Providers><main className=\"mx-auto max-w-7xl p-6\"><p className=\"mb-4 text-sm text-stone-600\">Local QA preview \u00b7 disposable test data</p><SewingPage/></main></Providers>);\n");
fs.writeFileSync(path.join(out,"navigation.ts"),"export const useParams = () => ({id: String((window as any).previewWorkOrderId)});\nexport const usePathname = () => \"/sewing-preview\";\nexport const useSearchParams = () => new URLSearchParams();\nexport const useRouter = () => ({ push: () => {}, replace: () => {}, refresh: () => {} });\n");
fs.writeFileSync(path.join(out,"link.tsx"),"import React from \"react\";\nexport default function Link({href,children,...props}:any) { return <a href={typeof href === \"string\" ? href : \"#\"} {...props}>{children}</a>; }\n");
await build({entryPoints:[path.join(out,"sewing-entry.tsx")],outfile:path.join(out,"sewing.js"),bundle:true,format:"iife",platform:"browser",jsx:"automatic",minify:true,
  tsconfig:path.join(root,"frontend/tsconfig.json"),nodePaths:[path.join(root,"frontend/node_modules")],define:{"process.env.NODE_ENV":'"production"'},
  alias:{"next/navigation":path.join(out,"navigation.ts"),"next/link":path.join(out,"link.tsx")}});
const staticHtml=fs.readFileSync(path.join(root,"frontend/.next/server/app/eco-fabric-transfers.html"),"utf8");
const css=[...staticHtml.matchAll(/<link[^>]*href="([^"]+\.css)"[^>]*>/g)].map(m=>m[0]).join("");
const fixture=JSON.parse(fs.readFileSync(path.join(out,"fixture.json")));
fs.writeFileSync(path.join(out,"sewing.html"),`<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>${css}</head><body><div id="root"></div><script>window.previewWorkOrderId=${fixture.workOrderId};</script><script src="/sewing-preview.js"></script></body></html>`);
