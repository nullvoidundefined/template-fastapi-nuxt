# Theme User Stories

## US-THEME-001: Choose a light or dark theme that survives a reload

**As** a visitor
**I want to** choose light, dark, or my operating system's theme, and keep that choice on every page load
**So that** the app is comfortable to read and never flashes the theme I did not choose

**Acceptance criteria:**

- [x] The default and protected layouts carry a labelled "Theme" select offering System, Light, and Dark.
- [x] A choice is saved to localStorage and applied as `data-theme` on `<html>`; System follows the operating system, live.
- [x] An inline script in the document head applies the stored theme before the app hydrates, so a reload paints the chosen theme first (spec B-37).
- [x] The server never renders a theme attribute, since it cannot read localStorage (spec B-37).

**E2E test:** `e2e/theme.spec.ts`
**Ticket:** IAN-337
