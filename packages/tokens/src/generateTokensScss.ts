/**
 * Turns the token object into SCSS: one CSS custom property per token inside a :root block.
 *
 * Every token group has a naming convention. Colors keep unprefixed names (--accent,
 * --foreground-muted) and every other group is prefixed with its singular name
 * (--font-size-body, --radius-card). Numeric sizes gain px; unitless numbers (font weights,
 * line heights) and string values are written as they are.
 */
import type { Tokens } from './tokens.js';

type TokenGroupName = keyof Tokens;
type TokenGroupConvention = { prefix: string; unit: string };

const tokenGroupConventions: Record<TokenGroupName, TokenGroupConvention> = {
    colors: { prefix: '', unit: '' },
    fontSizes: { prefix: 'font-size-', unit: 'px' },
    fontWeights: { prefix: 'font-weight-', unit: '' },
    letterSpacing: { prefix: 'letter-spacing-', unit: '' },
    lineHeights: { prefix: 'line-height-', unit: '' },
    radii: { prefix: 'radius-', unit: 'px' },
    spacing: { prefix: 'spacing-', unit: 'px' },
    transitions: { prefix: 'transition-', unit: '' },
};

const generatedFileHeader = [
    '// GENERATED FILE. Do not edit by hand.',
    '// Source: packages/tokens/src/tokens.ts',
    '// Regenerate: pnpm --filter @repo/tokens run build',
];

/** Return the whole SCSS file: the header comment and the :root block of custom properties. */
export function generateTokensScss(tokens: Tokens): string {
    const groupNames = Object.keys(tokens) as TokenGroupName[];
    const groupBlocks = groupNames.map((groupName) =>
        formatTokenGroup(groupName, tokens[groupName]),
    );
    return [...generatedFileHeader, ':root {', groupBlocks.join('\n\n'), '}', ''].join('\n');
}

/** Format one token group as a comment line followed by one declaration per token. */
function formatTokenGroup(groupName: TokenGroupName, groupTokens: object): string {
    const { prefix, unit } = tokenGroupConventions[groupName];
    const declarations = Object.entries(groupTokens).map(([tokenName, tokenValue]) => {
        const valueUnit = typeof tokenValue === 'number' ? unit : '';
        return `    --${prefix}${convertToKebabCase(tokenName)}: ${String(tokenValue)}${valueUnit};`;
    });
    return [`    // ${groupName}`, ...declarations].join('\n');
}

/** Convert a camelCase token name to the kebab-case a custom property uses. */
function convertToKebabCase(camelCaseName: string): string {
    return camelCaseName.replace(/([A-Z])/g, (upperLetter) => `-${upperLetter.toLowerCase()}`);
}
