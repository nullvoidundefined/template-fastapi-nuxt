/**
 * Sets `data-theme` on <html> from the stored preference, before the first paint (spec: B-37).
 *
 * This function's own source text is the inline boot script (`buildThemeBootScript`), so it must
 * stay self-contained: no imports and no references to anything outside its body. The browser
 * globals are reached through `globalThis` rather than by the bare names `window` and `document`,
 * because the server build defines those two names as `undefined`, and the server is where the
 * head, and so this source text, is rendered; the first end-to-end run shipped a script reading
 * `(void 0).matchMedia` for exactly that reason. Everything that touches storage is inside one try
 * block because storage access itself throws in some privacy modes, and a boot script that threw
 * would leave the page with no theme at all; the fallback is the operating system's preference.
 */

/** Read the stored preference and apply it, following the operating system when there is none. */
export function applyStoredTheme(storageKey: string, storage?: Storage): void {
    const browserGlobal = globalThis as unknown as Window;
    const prefersDark = browserGlobal.matchMedia('(prefers-color-scheme: dark)').matches;
    let themeName = prefersDark ? 'dark' : 'light';
    try {
        const storedPreference = (storage ?? browserGlobal.localStorage).getItem(storageKey);
        if (storedPreference === 'light' || storedPreference === 'dark') {
            themeName = storedPreference;
        }
    } catch {
        // Storage is unavailable; the operating system's theme already stands.
    }
    browserGlobal.document.documentElement.setAttribute('data-theme', themeName);
}
