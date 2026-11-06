import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

// Resolve exactly the same plugin list and stylesheet used by the app build.
export async function compileAppCss(root = process.cwd()) {
  const require = createRequire(path.join(root, 'package.json'));
  const postcss = require('postcss');
  const config = require(path.join(root, 'postcss.config.js'));
  const input = path.join(root, 'src/app/globals.css');
  const plugins = Object.entries(config.plugins).map(([name, options]) => require(name)(options));
  const result = await postcss(plugins).process(fs.readFileSync(input, 'utf8'), { from: input });
  return result.css;
}
