/** What the visitor chose: a fixed theme, or `system` to follow the operating system. */
export type ThemePreference = 'light' | 'dark' | 'system';

/** The theme actually applied to the document, which `system` resolves to. */
export type ThemeName = 'light' | 'dark';
