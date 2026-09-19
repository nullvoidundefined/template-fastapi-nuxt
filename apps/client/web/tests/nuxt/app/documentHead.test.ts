/**
 * Component tests for the document head of the landing page (story US-LANDING-001, spec B-49).
 * The rendered document must declare its language on <html> (WCAG 3.1.1, html-has-lang) and carry
 * a title naming the product (WCAG 2.4.2, document-title), both of which Lighthouse accessibility
 * scores. Unhead writes head changes to the DOM on a debounced flush rather than synchronously, so
 * each assertion polls the live happy-dom document until the flush lands or the poll times out.
 */
import { describe, it, expect } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import App from '~/app.vue';

const productName = 'template-fastapi-nuxt';

describe('document head', () => {
    it('US-LANDING-001: app.vue at / sets lang="en" on the <html> element (B-49, WCAG 3.1.1)', async () => {
        await renderSuspended(App, { route: '/' });

        await expect
            .poll(() => document.documentElement.getAttribute('lang'), { timeout: 2000 })
            .toBe('en');
    });

    it('US-LANDING-001: app.vue at / sets a document title naming the product (B-49, WCAG 2.4.2)', async () => {
        await renderSuspended(App, { route: '/' });

        await expect.poll(() => document.title, { timeout: 2000 }).toContain(productName);
    });
});
