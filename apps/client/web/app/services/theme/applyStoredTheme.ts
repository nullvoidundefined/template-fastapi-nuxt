/**
 * Sets `data-theme` on <html> from the stored preference, before the first paint (spec: B-37).
 *
 * This function's own source text is the inline boot script (`buildThemeBootScript`), so it must
 * stay self-contained: no imports, no references to anything outside its body, and nothing a
 * minifier could rename out from under it. Everything is inside one try block because storage
 * access itself throws in some privacy modes, and a boot script that threw would leave the page
 * with no theme at all; the fallback is the operating system's preference.
 */

/** Read the stored preference and apply it, following the operating system when there is none. */
export function applyStoredTheme(storageKey: string, storage?: Storage): void {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    let themeName = prefersDark ? 'dark' : 'light';
    try {
        const storedPreference = (storage ?? window.localStorage).getItem(storageKey);
        if (storedPreference === 'light' || storedPreference === 'dark') {
            themeName = storedPreference;
        }
    } catch {
        // Storage is unavailable; the operating system's theme already stands.
    }
    document.documentElement.setAttribute('data-theme', themeName);
}
