import fs from "node:fs";

function read(path) {
  return fs.readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
}

function requireText(source, text, message) {
  if (!source.includes(text)) throw new Error(message);
}

const sales = read("src/app/(app)/sales/price-requests/page.tsx");
const cutting = read("src/app/(app)/cutting/price-calculation/page.tsx");
const purchasing = read("src/app/(app)/purchasing/price-calculation/page.tsx");
const card = read("src/components/price-calculation/PriceRequestCard.tsx");
const images = read("src/components/ImageThumbnail.tsx");

requireText(sales, 'api.post("/api/price-calculation/requests", { model_id: draft.modelId })', "Sales must create price requests with the selected model only.");
if (/api\.post\([^\n]+kroy_no/.test(sales)) throw new Error("Sales must not own the Kroy number.");
requireText(cutting, "/api/cutting-passports?q=", "Cutting must look up an entered Kroy number in Cutting Passports.");
requireText(cutting, "/cutting`, {", "Cutting must save Kroy and cutting details through its own endpoint.");
requireText(cutting, '"manual"', "Cutting must keep a manual-entry fallback when no passport matches.");
if (/api\.patch\([^\n]+purchasing[\s\S]{0,160}kroy_no/.test(purchasing)) throw new Error("Purchasing must not update the Kroy number.");
requireText(card, "modelImageUrl", "Every shared department card must show the model picture.");
requireText(card, "variantImageUrl", "Every shared department card must show the variant picture.");
requireText(images, 'target="_blank"', "Picture previews must open in a new tab.");

console.log("Price calculation department workflow contract passed.");
