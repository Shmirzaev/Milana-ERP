import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const receivingPage = readFileSync("src/app/(app)/purchasing/receiving/page.tsx", "utf8");
const inventoryPage = readFileSync("src/app/(app)/inventory/page.tsx", "utf8");

assert.match(receivingPage, /batch_no: ""/,
  "Purchase receiving must leave the supplier batch number blank for manual entry");
assert.doesNotMatch(receivingPage, /batch_no: `\$\{order\.po_no\}-\$\{line\.id\}`/,
  "Purchase receiving must not reuse the internal purchase identifier as the supplier batch");
assert.match(receivingPage, /t\("field\.internalBatchNo"\)/,
  "Purchase receiving must label the separate internal batch number");
assert.match(receivingPage, /value=\{formatOrderReference\(receiveState\.order\.po_no\)\} title=\{receiveState\.order\.po_no\} readOnly/,
  "The internal purchase number must be visible and system-controlled");
assert.match(inventoryPage, /internal_batch_no\?: string \| null/,
  "Inventory must accept the internal batch number returned by the API");
assert.match(inventoryPage, /batch\.internal_batch_no/,
  "Inventory must render the separate internal batch number");
assert.doesNotMatch(receivingPage, /useSWR<Supplier\[\]>\(/,
  "Purchase receiving must not fetch the full supplier directory");
assert.match(receivingPage, /<SupplierAsyncSelect[\s\S]*selectedName=\{receiveState\.supplier_name\}/,
  "Purchase receiving must use paged supplier search and retain off-page selection names");
assert.match(receivingPage, /supplier_name: Number\(saved\.payload\.supplier_id \|\| 0\) === Number\(line\.supplier_id \|\| order\.supplier_id \|\| 0\)/,
  "Recovered receipt must use its supplier identity before reusing an order supplier name");

console.log("Purchase receipt batch identity contract passed.");
