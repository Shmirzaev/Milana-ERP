import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import * as lucide from 'lucide-react';

const root = path.resolve('..');
const entries = [];
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === '.next') continue;
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file);
    else if (/\.(?:[cm]?[jt]sx?)$/.test(entry.name)) inspect(file);
  }
}
function inspect(file) {
  if (file === path.resolve('scripts/test-lucide-exports.mjs')) return;
  const text = fs.readFileSync(file, 'utf8');
  if (!text.includes('lucide-react')) return;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  function visit(node) {
    if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument) && ts.isStringLiteral(node.argument.literal) && node.argument.literal.text.startsWith('lucide-react')) {
      throw new Error(`Review Lucide import type: ${path.relative(root, file)}`);
    }
    const moduleSpecifier = ts.isImportDeclaration(node) || ts.isExportDeclaration(node) ? node.moduleSpecifier :
      ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(source) === 'require') ? node.arguments[0] : undefined;
    if (moduleSpecifier && ts.isStringLiteralLike(moduleSpecifier) && (moduleSpecifier.text === 'lucide-react' || moduleSpecifier.text.startsWith('lucide-react/'))) {
      const location = `${path.relative(root, file)}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}`;
      assert(ts.isImportDeclaration(node) && moduleSpecifier.text === 'lucide-react', `Review unsupported Lucide import: ${location}`);
      const clause = node.importClause;
      if (clause?.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
        assert.equal(location, 'frontend/scripts/test-besttex-cutting.mjs:8', `Review namespace import: ${location}`);
        entries.push({ name: '*', local: clause.namedBindings.name.text, type: false, location });
        return;
      }
      assert(clause && !clause.name && clause.namedBindings && ts.isNamedImports(clause.namedBindings), `Review non-named Lucide import: ${location}`);
      for (const element of clause.namedBindings.elements) entries.push({ name: (element.propertyName || element.name).text, local: element.name.text, type: clause.isTypeOnly || element.isTypeOnly, location });
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
walk(root);
assert(entries.length > 0, 'Lucide inventory is empty');
const runtime = [...new Set(entries.filter(e => !e.type && e.name !== '*').map(e => e.name))].sort();
const missing = runtime.filter(name => !(name in lucide));
console.log(JSON.stringify({ entries, runtime, missing }, null, 2));
assert.deepEqual(missing, [], 'Lucide runtime exports are missing');
for (const name of runtime) {
  const svg = renderToStaticMarkup(React.createElement(lucide[name], { 'data-test-icon': name }));
  assert.match(svg, /^<svg\b/);
  assert.match(svg, /<\/(?:svg)>$/);
  assert.match(svg, /<(?:path|circle|line|polyline|polygon|rect|ellipse)\b/);
}
console.log(`Rendered ${runtime.length} real Lucide SVG exports from ${entries.length} imports`);
