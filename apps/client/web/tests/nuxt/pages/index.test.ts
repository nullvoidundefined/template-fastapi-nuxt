/**
 * Component tests for the landing page (story US-LANDING-001, spec B-49).
 * The page must name the product in its only <h1> and link to /login and /register by
 * accessible name, both on its own and when rendered through app.vue and the default layout.
 */
import { describe, it, expect } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen } from '@testing-library/vue';
import LandingPage from '~/pages/index.vue';
import App from '~/app.vue';

const productName = 'template-fastapi-nuxt';

describe('landing page', () => {
    it('US-LANDING-001: renders exactly one <h1> naming the product (B-49)', async () => {
        await renderSuspended(LandingPage, { route: '/' });

        const headings = screen.getAllByRole('heading', { level: 1 });

        expect(headings).toHaveLength(1);
        expect(headings[0]?.textContent).toContain(productName);
    });

    it('US-LANDING-001: links to /login by the accessible name "Log in" (B-49)', async () => {
        await renderSuspended(LandingPage, { route: '/' });

        const loginLink = screen.getByRole('link', { name: 'Log in' });

        expect(loginLink.getAttribute('href')).toBe('/login');
    });

    it('US-LANDING-001: links to /register by the accessible name "Register" (B-49)', async () => {
        await renderSuspended(LandingPage, { route: '/' });

        const registerLink = screen.getByRole('link', { name: 'Register' });

        expect(registerLink.getAttribute('href')).toBe('/register');
    });

    it('US-LANDING-001: app.vue at / renders the landing page inside the layout with one <h1> (B-49)', async () => {
        const { container } = await renderSuspended(App, { route: '/' });

        const headings = screen.getAllByRole('heading', { level: 1 });

        expect(container.querySelector('[data-test-id="landing-page"]')).not.toBeNull();
        expect(headings).toHaveLength(1);
        expect(headings[0]?.textContent).toContain(productName);
        expect(screen.getByRole('link', { name: 'Log in' }).getAttribute('href')).toBe('/login');
        expect(screen.getByRole('link', { name: 'Register' }).getAttribute('href')).toBe(
            '/register',
        );
    });
});
