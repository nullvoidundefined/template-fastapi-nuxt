/**
 * Tests for the theme toggle and its place in the default and protected layouts (spec: B-37, the
 * Frontend feature map's Theme row, slice 07).
 *
 * The toggle is a labelled native select, so it is keyboard-operable and announced as "Theme"
 * without any ARIA of its own. Choosing an option changes the shared preference, which the theme
 * plugin applies to <html>; the assertion reads that attribute, which is what the stylesheet reads.
 * Both layouts render the toggle in their header, the protected one whether or not the session
 * has resolved, so a signed-out visitor on a public page and a signed-in one both reach it.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { nextTick } from 'vue';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { fireEvent, screen } from '@testing-library/vue';

import ThemeToggle from '~/components/ThemeToggle/ThemeToggle.vue';
import DefaultLayout from '~/layouts/default.vue';
import ProtectedLayout from '~/layouts/protected.vue';
import { useThemePreference } from '~/composables/useThemePreference';

afterEach(async () => {
    useThemePreference().setThemePreference('system');
    await nextTick();
    window.localStorage.clear();
    vi.unstubAllGlobals();
});

describe('ThemeToggle', () => {
    it('B-37: offers light, dark, and system under the accessible name "Theme"', async () => {
        await renderSuspended(ThemeToggle);

        const themeSelect = screen.getByRole('combobox', { name: 'Theme' });
        const optionValues = [...(themeSelect as HTMLSelectElement).options].map(
            (option) => option.value,
        );
        expect(optionValues).toEqual(['system', 'light', 'dark']);
        expect((themeSelect as HTMLSelectElement).value).toBe('system');
    });

    it('B-37: choosing dark applies the dark theme to the document', async () => {
        await renderSuspended(ThemeToggle);

        await fireEvent.update(screen.getByRole('combobox', { name: 'Theme' }), 'dark');
        await nextTick();

        expect(useThemePreference().themePreference.value).toBe('dark');
        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });
});

describe('the layouts', () => {
    it('B-37: the default layout header carries the theme toggle', async () => {
        await renderSuspended(DefaultLayout);

        expect(screen.getByRole('combobox', { name: 'Theme' })).toBeTruthy();
    });

    it('B-37: the protected layout header carries the theme toggle before the session resolves', async () => {
        vi.stubGlobal('fetch', () => new Promise<Response>(() => undefined));

        await renderSuspended(ProtectedLayout);

        expect(screen.getByRole('combobox', { name: 'Theme' })).toBeTruthy();
    });
});
