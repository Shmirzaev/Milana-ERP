import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

// Read the same base + supplemental modules as i18n.tsx, without executing code.
export function runtimeMessages(language) {
  const messages = new Map();
  for (const part of ["base", "supplemental"]) {
    const file = path.resolve(import.meta.dirname, `../src/lib/i18n/locales/${language}-${part}.ts`);
    const source = ts.createSourceFile(file, fs.readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
    const exported = source.statements.find(ts.isExportAssignment);
    let expression = exported?.expression;
    while (expression && (ts.isAsExpression(expression) || ts.isSatisfiesExpression(expression))) expression = expression.expression;
    if (!expression || !ts.isObjectLiteralExpression(expression)) throw new Error(`Expected a locale object in ${file}`);
    for (const property of expression.properties) {
      if (!ts.isPropertyAssignment(property) || !ts.isStringLiteral(property.name) || !ts.isStringLiteral(property.initializer)) {
        throw new Error(`Expected literal translation strings in ${file}`);
      }
      messages.set(property.name.text, property.initializer.text);
    }
  }
  return messages;
}
