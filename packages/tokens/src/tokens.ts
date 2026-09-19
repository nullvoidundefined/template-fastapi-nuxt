/**
 * Design token source of truth.
 *
 * This file is the single place where all visual values are defined.
 * Do not hardcode colors, spacing, radii, or typography values anywhere else.
 *
 * After editing this file, run:
 *   pnpm --filter @repo/tokens run build
 *
 * This regenerates dist/_tokens.scss (CSS custom properties for web + extension)
 * and dist/index.js (direct import for mobile + programmatic use).
 */
export const tokens = {
    colors: {
        accent: '#bf4f10',
        accentHover: '#a8440c',
        accentLight: '#fdecd9',
        background: '#ffffff',
        backgroundTranslucent: 'rgba(255, 255, 255, 0.92)',
        border: '#ebebeb',
        error: '#ef4444',
        foreground: '#222222',
        foregroundMuted: '#717171',
        surface: '#f7f7f7',
        surfaceActive: '#e0e0e0',
        surfaceAlt: '#f0f0f0',
        surfaceHover: '#f0f0f0',
        white: '#ffffff',
    },
    fontSizes: {
        badge: 11,
        caption: 12,
        small: 13,
        body: 14,
        label: 15,
        subheading: 16,
        subtitle: 18,
        navLogo: 20,
        section: 28,
        heroMobile: 32,
        hero: 48,
    },
    fontWeights: {
        regular: 400,
        medium: 500,
        semibold: 600,
        bold: 700,
        black: 800,
    },
    letterSpacing: {
        heading: '-0.02em',
        hero: '-0.03em',
        uppercase: '0.05em',
    },
    lineHeights: {
        body: 1.5,
        hero: 1.1,
        paragraph: 1.6,
    },
    radii: {
        button: 10,
        card: 12,
        large: 16,
        pill: 20,
        standard: 8,
        subtle: 4,
    },
    spacing: {
        1: 4,
        2: 8,
        3: 12,
        4: 16,
        5: 20,
        6: 24,
        7: 28,
        8: 32,
        9: 40,
        10: 48,
        11: 64,
        12: 80,
    },
    transitions: {
        hover: '0.15s',
        state: '0.20s',
    },
} as const;

export type Tokens = typeof tokens;
export type ColorKey = keyof typeof tokens.colors;
export type SpacingKey = keyof typeof tokens.spacing;
