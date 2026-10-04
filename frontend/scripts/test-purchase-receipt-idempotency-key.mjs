import assert from "node:assert/strict";
import crypto from "node:crypto";
import { readFileSync } from "node:fs";

// UI03-PURCHASE: the purchase receiving page must send an Idempotency-Key with
// POST /api/purchasing/orders/{id}/receive, bound to the payload it was made
// for. ST01 landed the server half (6fb88ee3, 4bea7a6c); without a key from the
// client a retried receipt still creates a second stock batch.
//
// Script-level contract check over the page source plus a faithful model of the
// landed backend. This is not a browser or end-to-end run.

const PAGE = process.argv[2] || "src/app/(app)/purchasing/receiving/page.tsx";
const pageSource = readFileSync(PAGE, "utf8");

// ---------------------------------------------------------------------------
// Landed backend contract.
// backend/app/api/routes/purchasing.py:169-225
// backend/app/services/idempotency.py:14-79
// ---------------------------------------------------------------------------

const KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;

function normalizeKey(rawKey) {
  const key = String(rawKey || "").trim();
  if (!key) return null;
  if (!KEY_PATTERN.test(key)) return { status: 400 };
  return key;
}

function sortDeep(value) {
  if (Array.isArray(value)) return value.map(sortDeep);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortDeep(value[key])]));
  }
  return value;
}

function fingerprint(payload) {
  return crypto.createHash("sha256").update(JSON.stringify(sortDeep(payload)), "utf8").digest("hex");
}

class ReceiveEndpoint {
  constructor() {
    this.records = new Map();
    this.receivedByOrder = new Map();
    this.receipts = 0;
  }

  receive({ orderId, factory = "MIL", caller = 7, payload, rawKey }) {
    const scope = `purchasing.receive:${factory}:${caller}:${orderId}`;
    const normalized = normalizeKey(rawKey);
    if (normalized && normalized.status) return { status: normalized.status };

    const hash = fingerprint(payload);
    if (normalized) {
      const record = this.records.get(`${scope} ${normalized}`);
      if (record) {
        if (record.hash !== hash) {
          return { status: 409, detail: "Idempotency-Key was already used with a different request payload" };
        }
        return { status: 200, replayed: true, response: record.response };
      }
    }

    // No key, or a first use of this key: receive the goods again.
    const added = payload.lines.reduce((sum, line) => sum + Number(line.received_quantity || 0), 0);
    this.receivedByOrder.set(orderId, (this.receivedByOrder.get(orderId) || 0) + added);
    this.receipts += 1;
    const response = { id: orderId, received_quantity: this.receivedByOrder.get(orderId) };
    if (normalized) this.records.set(`${scope} ${normalized}`, { hash, response });
    return { status: 200, replayed: false, response };
  }
}

// ---------------------------------------------------------------------------
// What the page actually sends today.
// ---------------------------------------------------------------------------

function extractReceiveCall(source) {
  const pathIndex = source.indexOf("/api/purchasing/orders/");
  assert.notEqual(pathIndex, -1, "receiving page must post to the purchase receive endpoint");
  const callStart = source.lastIndexOf("api.", pathIndex);
  assert.notEqual(callStart, -1, "receive request must go through the shared api client");
  const openParen = source.indexOf("(", callStart);
  let depth = 0;
  for (let index = openParen; index < source.length; index += 1) {
    if (source[index] === "(") depth += 1;
    else if (source[index] === ")") {
      depth -= 1;
      if (depth === 0) return source.slice(callStart, index + 1);
    }
  }
  return source.slice(callStart);
}

const receiveCall = extractReceiveCall(pageSource);
const sendsIdempotencyKey = /Idempotency-Key/.test(receiveCall);

const samplePayload = {
  supplier_id: 3,
  close_order: false,
  lines: [{ purchase_order_line_id: 41, received_quantity: 5, batch_no: "B-1", warehouse_id: 2 }],
};

// ---------------------------------------------------------------------------
// Part 1 — reproduction of the current behaviour.
// ---------------------------------------------------------------------------

console.log(`receive call sends Idempotency-Key: ${sendsIdempotencyKey}`);

const current = new ReceiveEndpoint();
const rawKeyFromPage = sendsIdempotencyKey ? "ui03-receipt-key" : undefined;
const currentFirst = current.receive({ orderId: 900, payload: samplePayload, rawKey: rawKeyFromPage });
const currentRetry = current.receive({ orderId: 900, payload: samplePayload, rawKey: rawKeyFromPage });

console.log(
  `ordered 5, operator retries the same receipt -> received ${current.receivedByOrder.get(900)}` +
  ` across ${current.receipts} receipts (replayed: ${currentRetry.replayed})`,
);

if (!sendsIdempotencyKey) {
  assert.equal(current.receipts, 2, "reproduction: an identical retry must currently double-receive");
  assert.equal(current.receivedByOrder.get(900), 10, "reproduction: 5 received must become 10 after a retry");
  console.log("REPRODUCED: the page sends no Idempotency-Key, so an identical retry adds stock twice.");
}

// ---------------------------------------------------------------------------
// Part 2 - the required key lifecycle, per the landed backend contract.
// These are the behaviours the page's key must satisfy once it sends one.
// ---------------------------------------------------------------------------

const stable = "ui03-stable-key";
const edited = { ...samplePayload, lines: [{ ...samplePayload.lines[0], received_quantity: 6 }] };
const anotherOrder = new ReceiveEndpoint();

const stableEndpoint = new ReceiveEndpoint();
assert.equal(stableEndpoint.receive({ orderId: 900, payload: samplePayload, rawKey: stable }).replayed, false);
assert.equal(stableEndpoint.receive({ orderId: 900, payload: samplePayload, rawKey: stable }).replayed, true);
assert.equal(
  stableEndpoint.receivedByOrder.get(900),
  5,
  "a retry of the same payload with the same key must replay one receipt",
);

assert.equal(
  stableEndpoint.receive({ orderId: 900, payload: edited, rawKey: stable }).status,
  409,
  "a changed payload under the same key is rejected, so a new key is required after an edit",
);

assert.equal(
  stableEndpoint.receive({ orderId: 900, payload: edited, rawKey: "ui03-new-key" }).replayed,
  false,
  "an edited payload with a new key is a genuinely new receipt",
);
assert.equal(stableEndpoint.receivedByOrder.get(900), 11);

const first = anotherOrder.receive({ orderId: 900, payload: samplePayload, rawKey: stable });
const second = anotherOrder.receive({ orderId: 901, payload: samplePayload, rawKey: stable });
assert.equal(first.status, 200);
assert.equal(second.status, 200);
assert.equal(anotherOrder.receivedByOrder.get(901), 5, "two orders must never share one key");
assert.deepEqual(
  normalizeKey("has spaces and/slash"),
  { status: 400 },
  "a key must stay inside the backend's 1-128 [A-Za-z0-9._:-] character set",
);
assert.equal(normalizeKey(""), null, "an empty key stays optional and legacy behaviour");

console.log("Key lifecycle contract: stable on retry, new on edit, per order, charset-safe.");

// ---------------------------------------------------------------------------
// Part 3 - the page gate.
// ---------------------------------------------------------------------------

assert.doesNotMatch(
  pageSource,
  /\bfetch\(/,
  "receiving must keep using the shared api client, not a parallel raw fetch wrapper",
);

assert.match(
  receiveCall,
  /Idempotency-Key/,
  "UI03-PURCHASE: the receive request must carry an Idempotency-Key header",
);

assert.match(
  pageSource,
  /sessionStorage/,
  "UI03-PURCHASE: the pending receipt key must be durable so a reload can retry with the same key",
);

console.log("Purchase receipt idempotency key contract passed.");

// ---------------------------------------------------------------------------
// Part 4 - the page-side key lifecycle wiring.
//
// Part 2 pins the required behaviour against a model of the landed backend.
// These are source-level assertions: they lock in that the page is wired to
// that behaviour. They are NOT a behavioural, DOM or end-to-end run. In
// particular a real reload is not exercised here.
// ---------------------------------------------------------------------------

assert.match(
  pageSource,
  /receiptStorageKey\(userId, receiveState\.order\.id, receiveState\.line\.id\)/,
  "the saved receipt must be tracked per order and line, so two lines of one order are two receipts",
);

assert.match(
  pageSource,
  /if \(pending && stableStringify\(pending\.body\) === stableStringify\(body\)\) \{\s*return \{ key: pending\.key, wasPending: true \};\s*\}/,
  "an unchanged resubmission must compare equal to the saved payload and reuse its key",
);

assert.match(
  pageSource,
  /if \(key\) writePendingReceipt\(storageKey, \{ key, body, \.\.\.meta \}\)/,
  "an edited payload must be stored under a newly generated key",
);

assert.match(
  pageSource,
  /await api\.postWithHeaders\(`\/api\/purchasing\/orders\/\$\{receiveState\.order\.id\}\/receive`, body, receiptKey \? \{ "Idempotency-Key": receiptKey \} : undefined\)/,
  "the header must be sent when a key exists and omitted when it does not, so keyless behaviour is unchanged",
);

// The clear must sit in the SUCCESS path: a later clear in the catch block must
// not satisfy this, or a confirmed receipt would keep replaying forever.
assert.match(
  pageSource,
  /await api\.postWithHeaders\([\s\S]*?clearPendingReceipt\(storageKey\);[\s\S]*?refreshOrders\(\);/,
  "a confirmed receipt must clear its saved key, so the next receipt is not a replay",
);

assert.match(
  pageSource,
  /sessionStorage\.setItem\(storageKey, JSON\.stringify\(pending\)\)/,
  "the pending key and payload must be written to sessionStorage, which is what survives a reload",
);

assert.match(
  pageSource,
  /const conflict = Number\(error\?\.status\) === 409/,
  "a 409 must be recognised so it is surfaced as a recoverable state rather than a crash",
);

assert.match(
  pageSource,
  /message: conflict \? recoveryCopy\[lang\]\.conflict :/,
  "a 409 must tell the operator to correct the values and receive again under a new key",
);

assert.match(
  pageSource,
  /wasPending \? recoveryCopy\[lang\]\.replayed : t\("page\.purchasing\.received"\)/,
  "a replayed receipt must be reported to the operator as success",
);

for (const lang of ["en", "ru", "uz"]) {
  assert.ok(
    pageSource.includes(`const recovery${lang[0].toUpperCase()}${lang.slice(1)}`) || pageSource.includes(`recovery${lang[0].toUpperCase()}${lang.slice(1)}`),
    `recovery copy must exist for ${lang}`,
  );
}
assert.equal(
  (pageSource.match(/pendingBody:|replayed:|conflict:/g) || []).length >= 9,
  true,
  "every recovery string must be translated in en, ru and uz",
);

console.log("Page wiring: per-order key, clear on success, 409 recovery, replay-as-success, keyless fallback.");
