import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { needsRunningApp, runNodeTests } from "./run-node-tests.mjs";

test("node discovery runs quarantines, catches new failures and excludes app tests", () => {
  const root = mkdtempSync(path.join(os.tmpdir(), "frontend-node-runner-"));
  const scripts = path.join(root, "scripts");
  mkdirSync(scripts);
  try {
    writeFileSync(path.join(scripts, "test-pass.mjs"), "console.log('pass');\n");
    writeFileSync(path.join(scripts, "check-known.mjs"), "throw new Error('known baseline');\n");
    writeFileSync(path.join(scripts, "test-new-failure.mjs"), "throw new Error('new failure');\n");
    writeFileSync(path.join(scripts, "test-ui.browser.mjs"), "throw new Error('must not execute');\n");
    writeFileSync(path.join(scripts, "test-server.mjs"), "server.listen(0);\n");
    const quarantine = { "check-known.mjs": { owner: "Dilmurod", reason: "fixture", bug: "CI-TEST",
      signature: "known baseline", failures: ["check-known.mjs"] } };
    const results = runNodeTests(scripts, quarantine);
    assert.deepEqual(Object.fromEntries(results.map(row => [row.file, row.status])), {
      "check-known.mjs": "QUARANTINE_FAIL", "test-new-failure.mjs": "FAIL",
      "test-pass.mjs": "PASS", "test-server.mjs": "NEEDS_APP", "test-ui.browser.mjs": "NEEDS_APP",
    });
    writeFileSync(path.join(scripts, "check-known.mjs"), "throw new Error('different failure');\n");
    assert.equal(runNodeTests(scripts, quarantine)[0].status, "FAIL", "a quarantine must not hide a different failure");
    writeFileSync(path.join(scripts, "check-known.mjs"), "console.log('fixed');\n");
    assert.equal(runNodeTests(scripts, quarantine)[0].status, "QUARANTINE_PASS");
    const dual = 'import { test } from "node:test";\ntest("one", () => { throw new Error("known baseline"); });\ntest("two", () => { throw new Error("known baseline"); });\n';
    writeFileSync(path.join(scripts, "test-dual.mjs"), dual);
    const dualQuarantine = { ...quarantine, "test-dual.mjs": { ...quarantine["check-known.mjs"], failures: ["one", "two"] } };
    assert.equal(runNodeTests(scripts, dualQuarantine).find(row => row.file === "test-dual.mjs").status, "QUARANTINE_FAIL");
    writeFileSync(path.join(scripts, "test-dual.mjs"), dual.replace('test("two", () => { throw new Error("known baseline")', 'test("two", () => { throw new Error("new regression")'));
    assert.equal(runNodeTests(scripts, dualQuarantine).find(row => row.file === "test-dual.mjs").status, "FAIL",
      "one baseline failure must not mask a different error in another known test");
    assert.throws(() => runNodeTests(scripts, { "test-missing.mjs": quarantine["check-known.mjs"] }), /Stale quarantine/);
    assert(!needsRunningApp("test-fixture.mjs", 'const fixture = "server.listen(0); playwright";'));
    assert(needsRunningApp("test-other.mjs", 'import { chromium } from "playwright";'));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
