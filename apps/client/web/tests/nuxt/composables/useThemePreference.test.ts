/**
 * Tests for the theme preference composable and the client plugin that persists it (spec: B-37,
 * the Nuxt track's Theme section, slice 07).
 *
 * The composable holds the preference in `useState`, so every caller in one app shares it. The
 * plugin `plugins/theme.client.ts`, which the Nuxt test environment installs as the real app does,
 * writes each change to localStorage and applies it as `data-theme` on <html>, resolving `system`
 * through the operating system's preference. The assertions read localStorage and the live
 * document, which is what the next page load's boot script and the stylesheet will read.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { nextTick } from 'vue';

import { THEME_STORAGE_KEY } from '~/constants/theme';
import { useThemePreference } from '~/composables/useThemePreference';

afterEach(async () => {
    useThemePreference().setThemePreference('system');
    await nextTick();
    window.localStorage.clear();
});

describe('useThemePreference', () => {
    it('B-37: starts at system and is shared by every caller', () => {
        const first = useThemePreference();
        const second = useThemePreference();
        expect(first.themePreference.value).toBe('system');

        first.setThemePreference('dark');

        expect(second.themePreference.value).toBe('dark');
    });

    it('B-37: a chosen theme is persisted and applied to <html>', async () => {
        useThemePreference().setThemePreference('dark');
        await nextTick();

        expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('B-37: system is persisted as system and applied as the operating system theme', async () => {
        useThemePreference().setThemePreference('dark');
        await nextTick();
        useThemePreference().setThemePreference('system');
        await nextTick();

        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('system');
        expect(document.documentElement.getAttribute('data-theme')).toBe(
            prefersDark ? 'dark' : 'light',
        );
    });
});
