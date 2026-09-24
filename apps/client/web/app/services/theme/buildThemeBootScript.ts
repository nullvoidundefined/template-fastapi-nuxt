/**
 * Builds the inline script app.vue puts in the document head (spec: B-37).
 *
 * The script is `applyStoredTheme`'s source called with the storage key, so the logic a browser
 * runs before first paint is the same function the unit tests exercise, not a hand-copied string.
 */
import { THEME_STORAGE_KEY } from '~/constants/theme';
import { applyStoredTheme } from '~/services/theme/applyStoredTheme';

/** Return the self-invoking boot script's source text. */
export function buildThemeBootScript(): string {
    return `(${applyStoredTheme.toString()})(${JSON.stringify(THEME_STORAGE_KEY)});`;
}
