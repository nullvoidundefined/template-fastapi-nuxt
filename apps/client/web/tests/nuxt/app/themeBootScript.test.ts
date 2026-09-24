/**
 * Tests that app.vue puts the theme boot script into the document head (spec: B-37, the Nuxt
 * track's Theme section, slice 07).
 *
 * The script has to be inline and in the head, because it must set `data-theme` before the body is
 * painted; a script at the end of the body, or one loaded from a file, would run after the first
 * paint and the page would flash the other theme. The assertion reads the live document head for an
 * inline script whose text is exactly the boot script, polling because Unhead flushes head changes
 * on a debounce. That the server itself never renders a theme attribute, and that the attribute is
 * present before hydration, is asserted against the built server in `e2e/theme.spec.ts`.
 */
import { describe, it, expect } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';

import App from '~/app.vue';
import { buildThemeBootScript } from '~/services/theme/buildThemeBootScript';

/** Return the text of every inline script currently in the document head. */
function readInlineHeadScripts(): string[] {
    return [...document.head.querySelectorAll('script:not([src])')].map(
        (script) => script.textContent ?? '',
    );
}

describe('the theme boot script in the document head', () => {
    it('B-37: app.vue renders the boot script inline in <head>', async () => {
        await renderSuspended(App, { route: '/' });

        await expect
            .poll(() => readInlineHeadScripts(), { timeout: 2000 })
            .toContain(buildThemeBootScript());
    });
});
