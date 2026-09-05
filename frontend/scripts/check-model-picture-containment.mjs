import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const files = [
  "src/components/VerticalModelPhoto.tsx",
  "src/app/(app)/models/page.tsx",
  "src/app/(app)/models/[id]/page.tsx",
  "src/app/(app)/warehouse-stock/page.tsx",
];
const sources = files.map((file) => [file, fs.readFileSync(path.join(root, file), "utf8")]);
const errors = [];

const vertical = sources[0][1];
if (!vertical.includes('"h-full w-full object-contain"')) {
  errors.push("Vertical model photos must fit the complete source image.");
}
if (vertical.includes("rotate-90") || vertical.includes("object-cover")) {
  errors.push("Vertical model photos must not rotate or crop source images.");
}
if (!vertical.includes("adaptiveHeight") || !vertical.includes("block h-auto max-h-40 w-full object-contain")) {
  errors.push("Adaptive catalogue photos must use their meaningful source aspect ratio.");
}

const modelsPage = sources[1][1];
if (!modelsPage.includes("adaptiveHeight") || !modelsPage.includes("min-h-[128px]")) {
  errors.push("The model list must center adaptive-height photos without a forced portrait canvas.");
}

for (const [file, source] of sources.slice(1)) {
  if (!source.includes("object-contain")) {
    errors.push(`${file} must render model pictures with object-contain.`);
  }
}

const warehouse = sources[3][1];
if ((warehouse.match(/object-contain/g) || []).length < 2) {
  errors.push("Warehouse group and detail pictures must both fit the complete source image.");
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log("Model and warehouse picture containment contract OK");
