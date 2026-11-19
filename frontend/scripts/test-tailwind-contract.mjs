import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';

const req = createRequire(process.cwd() + '/package.json');
const postcss = req('postcss');
const config = req('./postcss.config.js');
const input = path.resolve('src/app/globals.css');
const source = fs.readFileSync(input, 'utf8');
const plugins = () => Object.entries(config.plugins).map(([name, options]) => req(name)(options));
const sibling = '&>:not([hidden])~:not([hidden])';
const gridCases = [
  ['src/app/(app)/attendance/page.tsx', '#dedbd0', true],
  ['src/app/(app)/traceability/page.tsx', '#ecebe3', false],
];

function verifyGrids(root, files = gridCases.map(([file]) => fs.readFileSync(file, 'utf8'))) {
  const baseline = postcss.parse(fs.readFileSync('scripts/tailwind-v3-grid-baseline.css', 'utf8'));
  for (const [selector, edge, zero] of [['.divide-x', 'left', false], ['.divide-y', 'top', false], ['.sm\\:divide-y-0', 'top', true]]) {
    let rule;
    baseline.walkRules(r => { if (r.selector.startsWith(selector + ' >')) rule = r; });
    assert(rule && /:not\(\[hidden\]\)\s*~\s*:not\(\[hidden\]\)/.test(rule.selector), `baseline ${selector} sibling`);
    const decl = rule.nodes.find(n => n.prop === `border-${edge}-width`);
    assert(decl && decl.value.includes(zero ? '0px' : '1px') && decl.value.includes('1 - var('), `baseline ${selector} edge`);
  }
  gridCases.forEach(([, color, responsive], index) => {
    const match = files[index].match(/<dl className="([^"]*\bgrid-cols-2\b[^"]*)"/);
    assert(match, `grid caller ${index}`);
    const classes = match[1].split(/\s+/);
    assert(!classes.some(c => /^(?:sm:)?divide-[xy](?:-|$)|^divide-\[/.test(c)), `grid caller ${index} must not use v4 divide`);
    const expected = [[`[${sibling}]:border-l`, 'border-left-width', '1px'], [`[${sibling}]:border-t`, 'border-top-width', '1px'], [`[${sibling}]:border-[${color}]`, 'border-color', color]];
    if (responsive) expected.push([`sm:[${sibling}]:border-t-0`, 'border-top-width', '0px']);
    for (const [token, prop, value] of expected) {
      assert(classes.includes(token), `grid caller ${index} missing ${token}`);
      let found = false;
      root.walkDecls(prop, decl => {
        const selectors = [], media = [];
        for (let node = decl.parent; node && node.type !== 'root'; node = node.parent) {
          if (node.type === 'rule') selectors.unshift(node.selector);
          if (node.type === 'atrule' && node.name === 'media') media.unshift(node.params);
        }
        const text = selectors.join(' ').replaceAll('\\', '').replace(/\s+/g, '');
        if (text.includes(token) && text.includes('>:not([hidden])~:not([hidden])') && decl.value.toLowerCase() === value && (!token.startsWith('sm:') || media.some(m => /40rem|640px/.test(m)))) found = true;
      });
      assert(found, `grid caller ${index} compiled ${token} ${prop}:${value}`);
    }
  });
  const dashboard = fs.readFileSync('src/components/dashboard/ManagementDashboard.tsx', 'utf8');
  const dashboardGrid = dashboard.match(/<div className="([^"]*grid-cols-2[^\"]*)" style=\{surface\}>/);
  assert(dashboardGrid, 'dashboard grid caller');
  const dashboardClasses = dashboardGrid[1].split(/\s+/);
  assert(!dashboardClasses.includes('divide-x'), 'dashboard must not use v4 divide-x');
  assert(dashboardClasses.includes(`[${sibling}]:border-l`), 'dashboard following-sibling left border');
  assert(dashboard.includes('style={{ borderColor: "var(--erp-border-soft)" }}'), 'dashboard cell border color');
}

function verify(root) {
  assert(root.toString().length > 10000, 'compiled CSS must not be empty');
  const rules = [];
  root.walkRules(rule => rules.push(rule));
  const ruleFor = selector => {
    const found = rules.find(rule => rule.selector === selector);
    assert(found, `missing ${selector}`);
    return found;
  };
  function declaration(selector, property, value) {
    const found = [];
    ruleFor(selector).walkDecls(property, decl => found.push(decl.value));
    assert(found.some(item => value.test(item)), `${selector} ${property}: ${found.join(', ')}`);
  }
  declaration('.btn', 'display', /inline-flex/);
  declaration('.card', 'overflow', /hidden/);
  declaration('.input', 'width', /100%/);
  declaration('.rounded', 'border-radius', /0\.25rem/);
  declaration('.text-brand-600', 'color', /brand-600|1d4ed8|29\s+78\s+216/i);
  const grid = ruleFor('.sm\\:grid-cols-2');
  assert(grid.nodes.some(node => node.prop === 'grid-template-columns' && /repeat\(2/.test(node.value)));
  let parent = grid.parent;
  while (parent && !(parent.type === 'atrule' && parent.name === 'media')) parent = parent.parent;
  assert(parent && /(?:40rem|640px)/.test(parent.params), 'sm grid must be inside the 640px media condition');
  for (const selector of ['.focus\\:outline-hidden', '.input']) {
    const declarations = [];
    root.walkDecls(decl => {
      const selectors = [], media = [];
      for (let node = decl.parent; node && node.type !== 'root'; node = node.parent) {
        if (node.type === 'rule') selectors.unshift(node.selector);
        if (node.type === 'atrule' && node.name === 'media') media.unshift(node.params);
      }
      const full = selectors.join(' ');
      if (full.includes(selector) && full.includes(':focus')) declarations.push({decl, full, media});
    });
    const normal = declarations.filter(item => !item.media.some(m => /forced-colors/.test(m)));
    const forced = declarations.filter(item => item.media.some(m => /forced-colors\s*:\s*active/.test(m)));
    assert(normal.some(({decl}) => decl.prop === 'outline-style' && decl.value === 'none'), `${selector} normal outline style`);
    const outlines = declarations.filter(({decl}) => decl.prop === 'outline' || decl.prop === 'outline-style');
    assert(outlines.length && outlines.at(-1).decl.prop === 'outline' && outlines.at(-1).decl.value === '2px solid transparent', `${selector} forced-colors outline: ${outlines.map(x => `${x.full} [${x.media}] ${x.decl.prop}:${x.decl.value}`).join(', ')}`);
    assert(forced.some(({decl}) => decl.prop === 'outline-offset' && decl.value === '2px'), `${selector} forced-colors offset`);
  }

}

async function main() {
  const result = await postcss(plugins()).process(source, {from: input});
  if (process.env.TAILWIND_CSS_RESULT) fs.writeFileSync(process.env.TAILWIND_CSS_RESULT, result.css);
  verify(result.root);
  verifyGrids(result.root);
  const missingEdge = result.root.clone();
  missingEdge.walkDecls('border-left-width', decl => { if (decl.value === '1px') decl.remove(); });
  assert.throws(() => verifyGrids(missingEdge), /compiled .*border-l/);
  const oldDivide = gridCases.map(([file]) => fs.readFileSync(file, 'utf8'));
  oldDivide[0] = oldDivide[0].replace('grid grid-cols-2', 'grid grid-cols-2 divide-x');
  assert.throws(() => verifyGrids(result.root, oldDivide), /must not use v4 divide/);
  const noForcedProtection = result.root.clone();
  noForcedProtection.walkAtRules('media', rule => { if (/forced-colors\s*:\s*active/.test(rule.params)) rule.remove(); });
  assert.throws(() => verify(noForcedProtection), /forced-colors outline/);
  const broken = result.root.clone();
  broken.walkRules('.text-brand-600', rule => rule.remove());
  assert.throws(() => verify(broken), /missing \.text-brand-600/);
  const withoutConfig = source.replace(/^@config\s+[^;]+;\s*$/m, '');
  assert.notEqual(withoutConfig, source, 'the actual config directive must be removed');
  const missingConfig = await postcss(plugins()).process(withoutConfig, {from: input});
  const brand = [];
  missingConfig.root.walkRules('.text-brand-600', rule => brand.push(rule));
  assert.equal(brand.length, 0, 'missing real config must remove brand utility');
  console.log('Tailwind project PostCSS contracts and missing-config compilation challenge passed');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
