import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { compileAppCss } from './lib/compile-app-css.mjs';

const require = createRequire(path.resolve('package.json'));
const postcss = require('postcss');
const input = path.resolve('src/app/globals.css');
const source = fs.readFileSync(input, 'utf8');

function hasRule(css, selector) {
  let found = false;
  postcss.parse(css).walkRules(selector, () => { found = true; });
  return found;
}

test('configured compiler emits real application utilities', async () => {
  const css = await compileAppCss();
  assert.ok(hasRule(css, '.flex'));
  assert.ok(hasRule(css, '.text-brand-600'));
});

test('legacy plugin and missing Tailwind config are detected', async () => {
  assert.throws(() => postcss([require('tailwindcss')()]), /PostCSS plugin/i);
  const withoutConfig = source.replace(/^@config\s+[^;]+;\s*$/m, '');
  assert.notEqual(withoutConfig, source);
  const config = require('./postcss.config.js');
  const plugins = Object.entries(config.plugins).map(([name, options]) => require(name)(options));
  const result = await postcss(plugins).process(withoutConfig, { from: input });
  assert.equal(hasRule(result.css, '.text-brand-600'), false);
});
