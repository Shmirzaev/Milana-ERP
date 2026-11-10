import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import test from 'node:test';
import { buildSync } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const bundled = buildSync({
  entryPoints: [resolve(root, 'src/components/hr/turnstile/turnstileLive.ts')],
  absWorkingDir: root, bundle: true, platform: 'node', format: 'cjs', write: false,
});
const compiledModule = { exports: {} };
vm.runInNewContext(bundled.outputFiles[0].text, {
  module: compiledModule, exports: compiledModule.exports, require: createRequire(import.meta.url), process: { env: {} },
});
const { withAcceptedLiveJob, LiveState } = compiledModule.exports;
const receipt = state => ({ id: 7, employee_id: 1, device_id: 2, action: 'observe', state,
  created_at: '2026-11-10T08:00:00Z', observation: null, profile_hash: null });
const context = jobs => ({ enabled: true, employee_no: 'SYNTHETIC', devices: [], profiles: [], jobs });

test('accepted retry replaces the stale Failed row even when no refresh arrives', () => {
  const prior = context([receipt(LiveState.Failed)]);
  const accepted = receipt(LiveState.Queued);
  const next = withAcceptedLiveJob(prior, accepted);
  assert.equal(next.jobs[0], accepted);
  assert.equal(prior.jobs[0].state, LiveState.Failed);
});
for (const state of [LiveState.Queued, LiveState.Processing, LiveState.Dispatching]) {
  test(`delayed ${state} receipt cannot erase already verified success`, () => {
    const verified = { ...receipt(LiveState.Succeeded), profile_hash: 'a'.repeat(64) };
    const next = withAcceptedLiveJob(context([verified]), receipt(state));
    assert.equal(next.jobs[0], verified);
  });
}
test('new receipt is visible without fabricating an observation or profile', () => {
  const prior = context([]);
  const accepted = receipt(LiveState.Queued);
  const next = withAcceptedLiveJob(prior, accepted);
  assert.equal(next.jobs[0], accepted);
  assert.equal(next.profiles, prior.profiles);
  assert.equal(next.devices, prior.devices);
  assert.equal(accepted.observation, null);
});
test('receipt replacement retains other jobs and does not duplicate the same ID', () => {
  const unrelated = { ...receipt(LiveState.Processing), id: 8, employee_id: 3 };
  const next = withAcceptedLiveJob(context([unrelated, receipt(LiveState.Failed)]), receipt(LiveState.Queued));
  assert.equal(next.jobs.length, 2);
  assert.equal(next.jobs[0], unrelated);
  assert.equal(next.jobs[1].state, LiveState.Queued);
});
test('absence of context does not invent enabled configuration', () => {
  assert.equal(withAcceptedLiveJob(undefined, receipt(LiveState.Queued)), undefined);
});
