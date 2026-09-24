/**
 * The theme's storage key, its choices, and the media query `system` follows (spec: B-37).
 *
 * The boot script in the document head and the client plugin both read the same key, so a theme
 * the plugin saved is the one the next page load paints first.
 */
import type { ThemePreference } from '~/types/themePreference';

export const THEME_STORAGE_KEY = 'theme-preference';
export const THEME_PREFERENCES: readonly ThemePreference[] = ['system', 'light', 'dark'];
export const DARK_COLOR_SCHEME_QUERY = '(prefers-color-scheme: dark)';
