import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const page = fs.readFileSync(path.join(root, "src/app/(app)/purchasing/page.tsx"), "utf8");
const dict = fs.readFileSync(path.join(root, "src/lib/i18n/dict.ts"), "utf8");

const requiredPageTokens = [
  "const [showRequestForm, setShowRequestForm] = useState(false)",
  "canRequest && !showRequestForm",
  "canRequest && showRequestForm",
  'new Set(["draft", "pending_approval", "approved"])',
  "grid grid-cols-1 gap-4 md:grid-cols-2",
  "filter((row) => row.id !== request.id)",
];
for (const token of requiredPageTokens) {
  if (!page.includes(token)) throw new Error(`Purchasing clean UI contract is missing: ${token}`);
}

for (const removedToken of ["ShortageRow", "purchasing-shortages:", "page.purchasing.shortagesTitle", "createRequestFromSalesOrder"]) {
  if (page.includes(removedToken)) throw new Error(`Removed purchasing UI is still present: ${removedToken}`);
}

for (const label of ["New request", "Новая заявка", "Namuna yaratish"]) {
  if (!dict.includes(label)) throw new Error(`Missing purchasing action translation: ${label}`);
}

console.log("Purchasing clean UI contract OK");
