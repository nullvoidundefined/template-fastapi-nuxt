/**
 * Build step: writes dist/_tokens.scss from the token source. The build script runs it after tsc,
 * and the web app imports the result through the package's `./scss` export.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { generateTokensScss } from './generateTokensScss.js';
import { tokens } from './tokens.js';

const outputPath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../dist/_tokens.scss',
);

mkdirSync(path.dirname(outputPath), { recursive: true });
writeFileSync(outputPath, generateTokensScss(tokens), 'utf8');
