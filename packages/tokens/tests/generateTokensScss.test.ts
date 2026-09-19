/**
 * Tests for the token SCSS generator (slice 01 PR 2, spec Architecture: packages/tokens).
 * Every token in the source must appear in the generated SCSS as a CSS custom property that
 * carries its value, so a token added to tokens.ts can never be silently dropped from the styles.
 * Expected names are derived from the exported tokens object, never from a hard-coded token list.
 */
import { describe, it, expect } from 'vitest';
import { generateTokensScss, tokens } from '../src/index';

type TokenGroupConvention = { prefix: string; unit: string };

// Naming convention per token group: colors keep the unprefixed names the styling track uses
// (--accent, --foreground-muted), and transitions keep the --transition-* names of the source template.
const tokenGroupConventions: Record<string, TokenGroupConvention> = {
    colors: { prefix: '', unit: '' },
    fontSizes: { prefix: 'font-size-', unit: 'px' },
    fontWeights: { prefix: 'font-weight-', unit: '' },
    letterSpacing: { prefix: 'letter-spacing-', unit: '' },
    lineHeights: { prefix: 'line-height-', unit: '' },
    radii: { prefix: 'radius-', unit: 'px' },
    spacing: { prefix: 'spacing-', unit: 'px' },
    transitions: { prefix: 'transition-', unit: '' },
};

function convertToKebabCase(camelCaseName: string): string {
    return camelCaseName.replace(/([A-Z])/g, (upperLetter) => `-${upperLetter.toLowerCase()}`);
}

function parseCustomProperties(scss: string): Map<string, string> {
    const customProperties = new Map<string, string>();
    for (const match of scss.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
        customProperties.set(match[1] as string, (match[2] as string).trim());
    }
    return customProperties;
}

function listExpectedProperties(): Array<{ name: string; value: string }> {
    const expectedProperties: Array<{ name: string; value: string }> = [];
    for (const [groupName, groupTokens] of Object.entries(tokens)) {
        const convention = tokenGroupConventions[groupName];
        if (!convention) {
            throw new Error(`No naming convention for token group "${groupName}"`);
        }
        for (const [tokenName, tokenValue] of Object.entries(groupTokens as object)) {
            const unit = typeof tokenValue === 'number' ? convention.unit : '';
            expectedProperties.push({
                name: `--${convention.prefix}${convertToKebabCase(tokenName)}`,
                value: `${String(tokenValue)}${unit}`,
            });
        }
    }
    return expectedProperties;
}

describe('generateTokensScss', () => {
    it('emits a CSS custom property carrying its value for every token in the source', () => {
        const customProperties = parseCustomProperties(generateTokensScss(tokens));
        const expectedProperties = listExpectedProperties();

        expect(expectedProperties.length).toBeGreaterThan(0);
        for (const { name, value } of expectedProperties) {
            expect(customProperties.get(name), name).toBe(value);
        }
    });

    it('declares the properties inside a :root block', () => {
        const scss = generateTokensScss(tokens);

        expect(scss).toMatch(/:root\s*\{[\s\S]*--accent\s*:[\s\S]*\}/);
    });

    it('emits no custom property that does not come from a token', () => {
        const customProperties = parseCustomProperties(generateTokensScss(tokens));
        const expectedNames = new Set(listExpectedProperties().map(({ name }) => name));

        expect([...customProperties.keys()].filter((name) => !expectedNames.has(name))).toEqual([]);
    });
});
