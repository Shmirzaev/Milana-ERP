import test from "node:test";
import assert from "node:assert/strict";
import { prepareEmployeePrintRows } from "../src/app/(app)/process-qr/employeePrint.ts";

test("prepares unique payloads once while retaining copy order", async () => {
  const calls = [];
  const rows = [{ payload: "0042", copy: 1 }, { payload: "0042", copy: 2 }, { payload: "A-3", copy: 1 }];
  const result = await prepareEmployeePrintRows(rows, async payload => { calls.push(payload); return `image:${payload}`; });
  assert.deepEqual(calls, ["0042", "A-3"]);
  assert.deepEqual(result.map(row => [row.payload, row.copy, row.qrImage]), [["0042", 1, "image:0042"], ["0042", 2, "image:0042"], ["A-3", 1, "image:A-3"]]);
});

test("rejects failed preparation and retries independently", async () => {
  let calls = 0;
  const encode = async () => { calls++; if (calls === 1) throw new Error("failed"); return "image"; };
  await assert.rejects(prepareEmployeePrintRows([{ payload: "1" }], encode));
  assert.equal((await prepareEmployeePrintRows([{ payload: "1" }], encode))[0].qrImage, "image");
  assert.equal(calls, 2);
});
