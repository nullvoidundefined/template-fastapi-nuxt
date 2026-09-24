/**
 * Resolves a theme preference to the theme the document shows (spec: B-37).
 */
import type { ThemeName, ThemePreference } from '~/types/themePreference';

/** Return the preference itself when it is fixed, else the operating system's theme. */
export function resolveThemeName(preference: ThemePreference, prefersDark: boolean): ThemeName {
    if (preference === 'system') {
        return prefersDark ? 'dark' : 'light';
    }
    return preference;
}
