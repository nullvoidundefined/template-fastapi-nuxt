/**
 * Tests that each auth page is wired to the gate (spec: slice 03 PR 3, B-12 and B-45, US-AUTH-003).
 *
 * A page that renders perfectly and forgot its `definePageMeta` is ungated, and no assertion about
 * what the page draws would catch it. So the first group reads the route records the application's
 * own router holds. Nuxt extracts the `middleware` key of `definePageMeta` into the route record at
 * build time, and `to.matched[].meta.middleware` is the only place the router looks for it when it
 * decides which middleware a navigation runs, so asserting there is asserting the thing the
 * framework actually reads rather than the text of a source file.
 *
 * The second group drives real navigations through that router, which is the strongest statement
 * available inside Vitest: the middleware is resolved by name, run by Nuxt, and the redirect it
 * returns is carried out by vue-router. B-45 names `/login` and `/register` separately because a
 * gate applied to one and not the other is the likely mistake, so both are navigated.
 *
 * The third group renders the application at each route. The layout half of `definePageMeta` is
 * not something the router exposes the way `middleware` is; what it changes is which layout wraps
 * the page, so it is asserted where it has an effect. That also pins the minimal permanent pages
 * PR 4 will build the forms into: one `<h1>` each, which the accessibility rules require anyway.
 */
import { describe, it, expect, afterEach, beforeAll, beforeEach } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen } from '@testing-library/vue';
import { useRouter } from '#app';

import App from '~/app.vue';

import {
    clearSessionCache,
    installBackendStub,
    planExpiredSession,
    planSignedInSession,
} from '../middleware/sessionGateHarness';

const signInPath = '/login';
const registerPath = '/register';
const dashboardPath = '/dashboard';
const requireSessionMiddlewareName = 'require-session';
const redirectIfSessionMiddlewareName = 'redirect-if-session';

/** Return the middleware names the route record for a path declares, whatever form they take. */
function readRouteMiddlewareNames(path: string): string[] {
    const routeRecord = useRouter()
        .getRoutes()
        .find((candidate) => candidate.path === path);
    if (!routeRecord) {
        throw new Error(`The application has no route record for ${path}`);
    }
    const declared = routeRecord.meta.middleware;
    if (!declared) {
        return [];
    }
    return (Array.isArray(declared) ? declared : [declared]).map(String);
}

/**
 * Navigate the application's router and return the path the visitor ended up on.
 *
 * Landing on a path only means something when there is a page there, so an unmatched destination
 * is reported as a failure rather than returned: vue-router will happily leave the visitor on
 * `/login` with nothing behind it, and a test that accepted that would pass against an application
 * with no sign-in page at all.
 */
async function navigateToPath(path: string): Promise<string> {
    const router = useRouter();
    await router.push(path);
    const landedRoute = router.currentRoute.value;
    if (landedRoute.matched.length === 0) {
        throw new Error(`The application has no page at ${landedRoute.path}`);
    }
    return landedRoute.path;
}

beforeAll(() => {
    installBackendStub();
});

beforeEach(async () => {
    planExpiredSession();
    await navigateToPath('/');
});

afterEach(async () => {
    await clearSessionCache();
});

describe('the auth pages declare their gate', () => {
    it('B-12: the dashboard route declares the require-session middleware', () => {
        expect(readRouteMiddlewareNames(dashboardPath)).toContain(requireSessionMiddlewareName);
    });

    it.each([signInPath, registerPath])(
        'B-45: the %s route declares the redirect-if-session middleware',
        (signedOutPath) => {
            expect(readRouteMiddlewareNames(signedOutPath)).toContain(
                redirectIfSessionMiddlewareName,
            );
        },
    );
});

describe('navigating with the gate in place', () => {
    it('B-12: a signed-out visitor navigating to the dashboard lands on the sign-in page', async () => {
        planExpiredSession();

        const landedOn = await navigateToPath(dashboardPath);

        expect(landedOn).toBe(signInPath);
    });

    it('B-12: a signed-in visitor navigating to the dashboard stays there', async () => {
        planSignedInSession();

        const landedOn = await navigateToPath(dashboardPath);

        expect(landedOn).toBe(dashboardPath);
    });

    it.each([signInPath, registerPath])(
        'B-45: a signed-in visitor navigating to %s lands on the dashboard',
        async (signedOutPath) => {
            planSignedInSession();

            const landedOn = await navigateToPath(signedOutPath);

            expect(landedOn).toBe(dashboardPath);
        },
    );

    it.each([signInPath, registerPath])(
        'B-45: a signed-out visitor navigating to %s stays there',
        async (signedOutPath) => {
            planExpiredSession();

            const landedOn = await navigateToPath(signedOutPath);

            expect(landedOn).toBe(signedOutPath);
        },
    );
});

describe('the auth pages render inside the layout they declare', () => {
    it('B-12: the dashboard renders its heading inside the protected layout', async () => {
        planSignedInSession();

        const { container } = await renderSuspended(App, { route: dashboardPath });

        expect(container.querySelector('[data-test-id="protected-layout"]')).not.toBeNull();
        const headings = screen.getAllByRole('heading', { level: 1 });
        expect(headings).toHaveLength(1);
        expect(headings[0]?.textContent).toContain('Dashboard');
    });

    it('B-45: the sign-in page renders its heading inside the auth layout', async () => {
        planExpiredSession();

        const { container } = await renderSuspended(App, { route: signInPath });

        expect(container.querySelector('[data-test-id="auth-layout"]')).not.toBeNull();
        const headings = screen.getAllByRole('heading', { level: 1 });
        expect(headings).toHaveLength(1);
        expect(headings[0]?.textContent).toContain('Log in');
    });

    it('B-45: the register page renders its heading inside the auth layout', async () => {
        planExpiredSession();

        const { container } = await renderSuspended(App, { route: registerPath });

        expect(container.querySelector('[data-test-id="auth-layout"]')).not.toBeNull();
        const headings = screen.getAllByRole('heading', { level: 1 });
        expect(headings).toHaveLength(1);
        expect(headings[0]?.textContent).toContain('Register');
    });
});
