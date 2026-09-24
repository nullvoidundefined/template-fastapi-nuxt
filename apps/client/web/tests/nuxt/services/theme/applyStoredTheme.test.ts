/**
 * Tests for the theme boot script and the resolver behind it (spec: B-37, slice 07).
 *
 * The boot script runs inline in the document head before first paint, so it cannot import
 * anything: it is the source text of `applyStoredTheme` called with the storage key. These tests
 * run that exact text, the way the browser will, against the live happy-dom document and its
 * localStorage, and assert the attribute it leaves on <html>. A stored `light` or `dark` wins; a
 * stored `system`, nothing stored, or a value the app never writes follows the operating system;
 * and a storage that throws, as a privacy mode's does, still leaves a theme rather than an error.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';

import { THEME_STORAGE_KEY } from '~/constants/theme';
import { applyStoredTheme } from '~/services/theme/applyStoredTheme';
import { buildThemeBootScript } from '~/services/theme/buildThemeBootScript';
import { resolveThemeName } from '~/services/theme/resolveThemeName';

/** Make `prefers-color-scheme: dark` report the given answer. */
function stubOperatingSystemTheme(prefersDark: boolean): void {
    vi.stubGlobal('matchMedia', (query: string) => ({
        matches: query === '(prefers-color-scheme: dark)' ? prefersDark : false,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
    }));
}

/** Run the boot script's source text as the browser would, with no module scope around it. */
function runBootScript(): void {
    new Function(buildThemeBootScript())();
}

afterEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    vi.unstubAllGlobals();
});

describe('resolveThemeName', () => {
    it('B-37: an explicit preference wins over the operating system', () => {
        expect(resolveThemeName('light', true)).toBe('light');
        expect(resolveThemeName('dark', false)).toBe('dark');
    });

    it('B-37: system follows the operating system', () => {
        expect(resolveThemeName('system', true)).toBe('dark');
        expect(resolveThemeName('system', false)).toBe('light');
    });
});

describe('the theme boot script', () => {
    it('B-37: sets data-theme from the stored preference before anything else runs', () => {
        stubOperatingSystemTheme(false);
        window.localStorage.setItem(THEME_STORAGE_KEY, 'dark');

        runBootScript();

        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('B-37: follows the operating system when nothing is stored', () => {
        stubOperatingSystemTheme(true);

        runBootScript();

        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('B-37: treats a value the app never writes as system', () => {
        stubOperatingSystemTheme(false);
        window.localStorage.setItem(THEME_STORAGE_KEY, '"><script>');

        runBootScript();

        expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('B-37: still sets a theme when storage throws', () => {
        stubOperatingSystemTheme(true);
        const throwingStorage = {
            getItem: () => {
                throw new Error('storage is disabled');
            },
        };

        applyStoredTheme(THEME_STORAGE_KEY, throwingStorage as unknown as Storage);

        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });
});
