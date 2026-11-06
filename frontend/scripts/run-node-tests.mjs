import assert from "node:assert/strict";
import ts from "typescript";
import { appendFileSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

export function needsRunningApp(name, source) {
  if (/(?:\.browser|-browser)\.mjs$/.test(name)) return true;
  const file = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  let needsApp = false;
  const browserModule = node => node && ts.isStringLiteral(node)
    && /^(?:playwright|@playwright\/test|puppeteer)(?:\/|$)/.test(node.text);
  function visit(node) {
    if (ts.isImportDeclaration(node) && browserModule(node.moduleSpecifier)) needsApp = true;
    if (ts.isCallExpression(node)) {
      if ((node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(file) === "require")
          && browserModule(node.arguments[0])) needsApp = true;
      if (ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "listen") needsApp = true;
      if (["spawn", "spawnSync", "execFile", "execFileSync"].includes(node.expression.getText(file))
          && /["'](?:next|uvicorn|dev|start)["']/.test(node.arguments.map(arg => arg.getText(file)).join(" "))) needsApp = true;
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return needsApp;
}

export function runNodeTests(directory, quarantine) {
  const files = readdirSync(directory).filter(name => /^(?:test|check)-.*\.mjs$/.test(name)).sort();
  for (const [file, entry] of Object.entries(quarantine)) {
    assert(files.includes(file), `Stale quarantine entry: ${file}`);
    assert(["Dilmurod", "Ismail", "Mirshoir"].includes(entry.owner), `Missing owner: ${file}`);
    assert(entry.reason && entry.bug && entry.signature && entry.failures?.length, `Incomplete quarantine: ${file}`);
  }
  const env = { ...process.env };
  // Nested harness fixtures must start a fresh Node test runner.
  delete env.NODE_TEST_CONTEXT;
  return files.map(file => {
    const entry = quarantine[file];
    if (needsRunningApp(file, readFileSync(path.join(directory, file), "utf8"))) {
      assert(!entry, `App-dependent test cannot be quarantined as node-only: ${file}`);
      console.log(`NEEDS_APP ${file}`);
      return { file, status: "NEEDS_APP" };
    }
    const result = spawnSync(process.execPath, ["--test", "--test-reporter=tap", path.join(directory, file)], {
      cwd: path.dirname(directory), env, encoding: "utf8", timeout: 90_000, maxBuffer: 8 * 1024 * 1024,
    });
    const output = (result.stdout || "") + (result.stderr || "");
    const failed = [...output.matchAll(/^not ok \d+ - (.+)$/gm)];
    const failures = failed.map((match, index) => {
      const name = match[1] === path.join(directory, file) ? file : match[1];
      const block = output.slice(match.index, failed[index + 1]?.index ?? output.length).split("\n# Subtest:")[0];
      // Standalone assertion errors precede Node's single file-wrapper TAP block.
      return { name, diagnostic: name === file && failed.length === 1 ? output : block };
    });
    let status = result.status === 0 && !result.error && /^# tests [1-9]\d*$/m.test(output) ? (entry ? "QUARANTINE_PASS" : "PASS") : "FAIL";
    if (status === "FAIL" && entry && !result.error && !result.signal && failures.length
        && failures.every(failure => entry.failures.includes(failure.name) && failure.diagnostic.includes(entry.signature))) {
      status = "QUARANTINE_FAIL";
    }
    console.log(`${status} ${file}${entry ? ` — ${entry.owner}; ${entry.bug}; ${entry.reason}` : ""}`);
    if (status === "FAIL" || status === "QUARANTINE_FAIL") console.log(output, result.error || "");
    return { file, status, owner: entry?.owner, bug: entry?.bug };
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const directory = path.dirname(fileURLToPath(import.meta.url));
  const quarantine = JSON.parse(readFileSync(path.join(directory, "node-test-quarantine.json"), "utf8"));
  const results = runNodeTests(directory, quarantine);
  const counts = results.reduce((all, row) => ({ ...all, [row.status]: (all[row.status] || 0) + 1 }), {});
  console.log("Node-only frontend test summary:", JSON.stringify(counts));
  if (process.env.GITHUB_STEP_SUMMARY) {
    const rows = results.map(row => `| ${row.file} | ${row.status} | ${row.owner || ""} | ${row.bug || ""} |`).join("\n");
    appendFileSync(process.env.GITHUB_STEP_SUMMARY,
      `\n## Node-only frontend tests\n\n${JSON.stringify(counts)}\n\n| Script | Result | Quarantine owner | Bug |\n| --- | --- | --- | --- |\n${rows}\n`);
  }
  for (const row of results.filter(row => row.status !== "PASS" && row.status !== "NEEDS_APP")) {
    const level = row.status === "FAIL" ? "error" : "warning";
    console.log(`::${level} file=frontend/scripts/${row.file}::${row.status}; ${row.owner || "unquarantined"}; ${row.bug || "new failure"}`);
  }
  process.exitCode = counts.FAIL ? 1 : 0;
}
