import fs from "node:fs";
import path from "node:path";
import { runtimeMessages } from "./runtime-locales.mjs";

const root = path.resolve(import.meta.dirname, "..");
const languages = ["en", "ru", "uz"];

const messages = Object.fromEntries(languages.map((lang) => [lang, runtimeMessages(lang)]));

const errors = [];
for (const lang of languages.slice(1)) {
  for (const key of messages.en.keys()) {
    if (!messages[lang].has(key)) errors.push(`${lang} is missing ${key}`);
  }
}

function placeholders(value) {
  return [...value.matchAll(/\{([^}]+)\}/g)].map((match) => match[1]).sort().join(",");
}
for (const [key, english] of messages.en) {
  for (const lang of languages.slice(1)) {
    const translated = messages[lang].get(key);
    if (translated && placeholders(translated) !== placeholders(english)) {
      errors.push(`${lang}.${key} has different placeholders`);
    }
  }
}

const sourceFiles = [];
function walk(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) walk(target);
    else if (/\.tsx?$/.test(entry.name)) sourceFiles.push(target);
  }
}
walk(path.join(root, "src"));

for (const file of sourceFiles) {
  const source = fs.readFileSync(file, "utf8");
  for (const match of source.matchAll(/\bt\(\s*["'`]([^"'`]+)["'`]/g)) {
    const key = match[1];
    if (!key.includes("${") && !messages.en.has(key)) {
      errors.push(`${path.relative(root, file)} uses missing key ${key}`);
    }
  }
}

if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}

console.log(`i18n OK: ${messages.en.size} keys in ${languages.join(", ")}`);
