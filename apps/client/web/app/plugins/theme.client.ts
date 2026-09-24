/**
 * Persists the theme preference and applies it to <html> in the browser (spec: B-37).
 *
 * The stored choice is loaded on `app:mounted`, after hydration, so the markup the server rendered
 * for the default `system` hydrates without a mismatch; the boot script in the head has already
 * painted the stored theme, so loading it late costs no flash. From then on every change is
 * written to localStorage and applied as `data-theme`, and while the preference is `system` a
 * change in the operating system's scheme is followed live.
 */
import { defineNuxtPlugin } from '#app';
import { watch } from 'vue';

import { DARK_COLOR_SCHEME_QUERY, THEME_PREFERENCES, THEME_STORAGE_KEY } from '~/constants/theme';
import { useThemePreference } from '~/composables/useThemePreference';
import { resolveThemeName } from '~/services/theme/resolveThemeName';
import type { ThemePreference } from '~/types/themePreference';

export default defineNuxtPlugin((nuxtApp) => {
    const { themePreference, setThemePreference } = useThemePreference();
    const darkSchemeQuery = window.matchMedia(DARK_COLOR_SCHEME_QUERY);

    function applyThemePreference(): void {
        const themeName = resolveThemeName(themePreference.value, darkSchemeQuery.matches);
        document.documentElement.setAttribute('data-theme', themeName);
    }

    watch(themePreference, (preference) => {
        writeStoredThemePreference(preference);
        applyThemePreference();
    });
    darkSchemeQuery.addEventListener?.('change', applyThemePreference);
    nuxtApp.hook('app:mounted', () => {
        setThemePreference(readStoredThemePreference());
        applyThemePreference();
    });
});

/** Return the stored preference, or `system` when none is stored or storage is unavailable. */
function readStoredThemePreference(): ThemePreference {
    try {
        const storedPreference = window.localStorage.getItem(THEME_STORAGE_KEY);
        return THEME_PREFERENCES.find((preference) => preference === storedPreference) ?? 'system';
    } catch {
        return 'system';
    }
}

/** Save the preference, doing nothing when storage is unavailable. */
function writeStoredThemePreference(preference: ThemePreference): void {
    try {
        window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    } catch {
        // Storage is unavailable; the choice lasts for this page only.
    }
}
