import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const receivePage = readFileSync(new URL("../src/app/(app)/inventory/receive/page.tsx", import.meta.url), "utf8");
const inventoryPage = readFileSync(new URL("../src/app/(app)/inventory/page.tsx", import.meta.url), "utf8");
const sidebar = readFileSync(new URL("../src/components/Sidebar.tsx", import.meta.url), "utf8");
const runtimeLocales = ["en", "ru", "uz"].map((language) => (
  readFileSync(new URL(`../src/lib/i18n/locales/${language}-base.ts`, import.meta.url), "utf8")
));

assert.match(receivePage, /searchParams\.get\("group"\) === "accessories"/);
assert.match(receivePage, /`\/api\/inventory\/items\?group=\$\{receiveGroup\}`/);
assert.match(receivePage, /`\/api\/inventory\/batches\?group=\$\{receiveGroup\}`/);
assert.match(receivePage, /"fabric_storage" : "accessory_storage"/);
assert.match(receivePage, /showFabricDetails=\{isFabricReceiving\}/);
assert.match(receivePage, /\{isAccessoryReceiving && \(\s*<StockForm/);
assert.match(receivePage, /\{isAccessoryReceiving && \(\s*<form onSubmit=\{submitAccessoryIssue\}/);

assert.match(sidebar, /\/inventory\/receive\?group=materials/);
assert.match(sidebar, /\/inventory\/receive\?group=accessories/);
assert.match(sidebar, /inventoryReceiveGroupMismatch/);
assert.doesNotMatch(sidebar, /href: "\/inventory\/receive", labelKey: "nav\.receive"/);

assert.doesNotMatch(inventoryPage, /GROUPS\.map\(\(option\)/);

for (const locale of runtimeLocales) {
  assert.match(locale, /"nav\.receiveFabric":/);
  assert.match(locale, /"nav\.receiveAccessories":/);
  assert.match(locale, /"page\.receiveStock\.fabricTitle":/);
  assert.match(locale, /"page\.receiveStock\.accessoryTitle":/);
}

console.log("Inventory receiving and storage separation contract passed.");
