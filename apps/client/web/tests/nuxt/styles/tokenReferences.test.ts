/**
 * Guard test for design-token references in the web app (story US-LANDING-001, spec Architecture:
 * packages/tokens). Every var(--name) used by a component or stylesheet under app/ must name a
 * custom property that @repo/tokens generates, so a typo or a token removed from tokens.ts fails
 * here instead of silently rendering with the browser's fallback. Styles may live in <style>
 * blocks or in sibling *.module.scss files, so every .vue and .scss file under app/ is scanned.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { generateTokensScss, tokens } from '@repo/tokens';

const appDirectory = resolve(import.meta.dirname, '../../../app');
const styledFilePattern = /\.(vue|scss)$/;

function listStyledFiles(directory: string): string[] {
    return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
        const entryPath = join(directory, entry.name);
        if (entry.isDirectory()) {
            return listStyledFiles(entryPath);
        }
        return styledFilePattern.test(entry.name) ? [entryPath] : [];
    });
}

function collectVariableReferences(): Array<{ name: string; file: string }> {
    return listStyledFiles(appDirectory).flatMap((file) =>
        [...readFileSync(file, 'utf8').matchAll(/var\(\s*(--[A-Za-z0-9_-]+)/g)].map((match) => ({
            name: match[1] as string,
            file,
        })),
    );
}

function collectDeclaredProperties(): Set<string> {
    const scss = generateTokensScss(tokens);
    return new Set(
        [...scss.matchAll(/(--[A-Za-z0-9_-]+)\s*:/g)].map((match) => match[1] as string),
    );
}

describe('design-token references', () => {
    it('US-LANDING-001: every var(--name) under app/ is declared by @repo/tokens', () => {
        const variableReferences = collectVariableReferences();
        const declaredProperties = collectDeclaredProperties();

        expect(variableReferences.length).toBeGreaterThan(0);
        const undeclaredReferences = variableReferences
            .filter(({ name }) => !declaredProperties.has(name))
            .map(({ name, file }) => `${name} in ${file.slice(appDirectory.length + 1)}`);
        expect(undeclaredReferences).toEqual([]);
    });
});
