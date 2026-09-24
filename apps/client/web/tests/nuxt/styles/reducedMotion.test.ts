/**
 * Guard test for B-48's reduced-motion half (spec: B-48, slice 03 PR 4, CLAUDE-STYLING.md).
 *
 * B-48 says that with `prefers-reduced-motion: reduce` no element animates, and the shared
 * conventions say the rule is `animation: none`, never a shortened duration, because a 0.01s
 * animation still moves and still triggers the vestibular reaction the preference exists to
 * prevent.
 *
 * This is asserted against the compiled stylesheet rather than against the DOM, and that choice is
 * deliberate. Vitest resolves a `*.module.scss` import to a proxy of class names and never
 * compiles or attaches the CSS, happy-dom evaluates no media queries and has no way to be told the
 * visitor prefers reduced motion, and `getComputedStyle` therefore reports the same empty
 * animation whether the rule is there or missing. A DOM assertion would pass for a component with
 * no reduced-motion rule at all, which is exactly the failure this test exists to catch, so it
 * would be a test that only appears to test something. The stylesheet is compiled with sass here
 * so that nesting, mixins and variables are resolved and what is read is the cascade a browser
 * would receive. The end-to-end half, that a real browser with the preference set paints no
 * motion, belongs to the Playwright run, which can emulate the preference.
 *
 * The second test keeps the first from passing vacuously: a guard over animating stylesheets says
 * nothing when nothing animates, and the kit's overlays (the modal and the toast) are the surfaces
 * that enter and leave, so at least one of them has to declare an animation for B-48 to mean
 * anything here.
 */
import { existsSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { describe, it, expect } from 'vitest';
import { compile } from 'sass';
import type { FileImporter } from 'sass';

const appDirectory = resolve(import.meta.dirname, '../../../app');
const uiKitDirectory = join(appDirectory, 'components');
const stylesheetPattern = /\.module\.scss$/;
const reducedMotionQuery = 'prefers-reduced-motion';
const animationPropertyPattern = /(animation[a-z-]*)\s*:\s*([^;}]+)/g;
const keyframesPattern = /@keyframes\s/;

const resolvePackageFile = createRequire(import.meta.url);

/** Resolve `@use '@repo/tokens/scss'` the way Vite does, so a stylesheet compiles on its own. */
const packageImporter: FileImporter<'sync'> = {
    findFileUrl(url) {
        if (!url.startsWith('@')) {
            return null;
        }
        return pathToFileURL(resolvePackageFile.resolve(url));
    },
};

function listStylesheets(directory: string): string[] {
    if (!existsSync(directory)) {
        return [];
    }
    return readdirSync(directory, { withFileTypes: true }).flatMap(function readEntry(entry) {
        const entryPath = join(directory, entry.name);
        if (entry.isDirectory()) {
            return listStylesheets(entryPath);
        }
        return stylesheetPattern.test(entry.name) ? [entryPath] : [];
    });
}

function compileStylesheet(file: string): string {
    return compile(file, { importers: [packageImporter] }).css;
}

/** The body of every `@media (prefers-reduced-motion: reduce)` block, brace-matched. */
function extractReducedMotionBlocks(css: string): string[] {
    const blocks: string[] = [];
    let searchFrom = 0;
    while (searchFrom < css.length) {
        const queryIndex = css.indexOf(reducedMotionQuery, searchFrom);
        if (queryIndex === -1) {
            break;
        }
        const blockStart = css.indexOf('{', queryIndex);
        if (blockStart === -1) {
            break;
        }
        let depth = 0;
        let cursor = blockStart;
        while (cursor < css.length) {
            const character = css[cursor];
            if (character === '{') {
                depth += 1;
            } else if (character === '}') {
                depth -= 1;
                if (depth === 0) {
                    break;
                }
            }
            cursor += 1;
        }
        blocks.push(css.slice(blockStart + 1, cursor));
        searchFrom = cursor + 1;
    }
    return blocks;
}

/** The same css with those blocks cut out, which is what the stylesheet says by default. */
function stripReducedMotionBlocks(css: string): string {
    return extractReducedMotionBlocks(css).reduce(function cutBlock(remaining, block) {
        return remaining.replace(block, '');
    }, css);
}

function readAnimationDeclarations(css: string): Array<{ property: string; value: string }> {
    return [...css.matchAll(animationPropertyPattern)].map(function readDeclaration(match) {
        return { property: match[1] ?? '', value: (match[2] ?? '').trim() };
    });
}

function hasMotionByDefault(css: string): boolean {
    const defaultCss = stripReducedMotionBlocks(css);
    if (keyframesPattern.test(defaultCss)) {
        return true;
    }
    return readAnimationDeclarations(defaultCss).some(function isMotion({ property, value }) {
        return property === 'animation' || property === 'animation-name' ? value !== 'none' : true;
    });
}

/** Why this stylesheet fails B-48, or an empty string when it honours the preference. */
function describeReducedMotionFault(file: string, css: string): string {
    const blocks = extractReducedMotionBlocks(css);
    if (blocks.length === 0) {
        return `${file} animates but has no (prefers-reduced-motion: reduce) rule`;
    }
    const declarations = blocks.flatMap(readAnimationDeclarations);
    if (declarations.length === 0) {
        return `${file} has a reduced-motion rule that never sets animation`;
    }
    const wrongDeclarations = declarations.filter(function isWrong({ property, value }) {
        const switchesOff = property === 'animation' || property === 'animation-name';
        return !switchesOff || value !== 'none';
    });
    if (wrongDeclarations.length > 0) {
        const spelled = wrongDeclarations
            .map(function spell({ property, value }) {
                return `${property}: ${value}`;
            })
            .join(', ');
        return `${file} shortens motion instead of switching it off (${spelled})`;
    }
    return '';
}

describe('reduced motion', () => {
    it('B-48: every animating stylesheet switches animation off under prefers-reduced-motion', () => {
        const faults = listStylesheets(appDirectory)
            .map(function readCompiled(file) {
                return { file: file.slice(appDirectory.length + 1), css: compileStylesheet(file) };
            })
            .filter(function animates({ css }) {
                return hasMotionByDefault(css);
            })
            .map(function describeFault({ file, css }) {
                return describeReducedMotionFault(file, css);
            })
            .filter(function isFault(fault) {
                return fault !== '';
            });

        expect(faults).toEqual([]);
    });

    it('B-48: the kit has motion for the preference to switch off', () => {
        const animatingStylesheets = listStylesheets(uiKitDirectory).filter(
            function animates(file) {
                return hasMotionByDefault(compileStylesheet(file));
            },
        );

        expect(animatingStylesheets).not.toHaveLength(0);
    });
});
