/**
 * Tests for the dashboard's billing buttons (spec: B-50's billing half, B-33, B-22, US-BILLING).
 *
 * The application is rendered at `/dashboard` with the real router, gate and API client; only
 * `fetch` is stubbed. Leaving for Stripe goes through `openExternalUrl`, which is replaced by a
 * recorder, because a test environment cannot follow a cross-origin navigation; what is asserted
 * is the URL the page would have sent the browser to.
 */
import { describe, it, expect, afterEach, beforeAll, vi } from 'vitest';
import { mockNuxtImport, renderSuspended } from '@nuxt/test-utils/runtime';
import { screen, fireEvent, waitFor } from '@testing-library/vue';
import { useRouter } from '#app';

import App from '~/app.vue';

import { clearSessionCache, signedInUser } from '../middleware/sessionGateHarness';

type PlannedResponse = { status: number; body?: unknown };

const checkoutUrl = 'https://checkout.stripe.test/c/pay/cs_test_1';
const portalUrl = 'https://billing.stripe.test/p/session/bps_test_1';
const configuredPriceId = 'price_template1';
const openedUrls: string[] = [];

vi.mock('~/services/navigation/openExternalUrl', () => ({
    openExternalUrl: (url: string) => {
        openedUrls.push(url);
    },
}));

mockNuxtImport('useRuntimeConfig', (original) => () => {
    const runtimeConfig = original();
    return {
        ...runtimeConfig,
        public: { ...runtimeConfig.public, stripePriceId: 'price_template1' },
    };
});

let plannedResponses: Record<string, PlannedResponse> = {};
let sentRequests: Request[] = [];

/** Answer from the plan keyed by `METHOD /path`; the session always resolves as signed in. */
async function answerByRoute(
    input: Parameters<typeof fetch>[0],
    init?: RequestInit,
): Promise<Response> {
    const sentRequest = new Request(input, init);
    sentRequests.push(sentRequest.clone());
    const routeKey = `${sentRequest.method} ${new URL(sentRequest.url).pathname}`;
    const fallback: PlannedResponse =
        routeKey === 'GET /api/v1/auth/me'
            ? { status: 200, body: { data: { ...signedInUser, role: 'member' } } }
            : { status: 404, body: { code: 'ROUTING_NOT_FOUND', error: 'Not found' } };
    const { status, body } = plannedResponses[routeKey] ?? fallback;
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

/** Return the requests sent to `METHOD /path`. */
function readSentRequests(routeKey: string): Request[] {
    return sentRequests.filter(
        (candidate) => `${candidate.method} ${new URL(candidate.url).pathname}` === routeKey,
    );
}

/** Press the named button, failing as an assertion when the page has none. */
async function pressButton(name: string): Promise<void> {
    const namedButton = screen.queryByRole('button', { name });
    expect(namedButton, `no button named "${name}"`).not.toBeNull();
    await fireEvent.click(namedButton!);
}

beforeAll(() => {
    vi.stubGlobal('fetch', answerByRoute);
});

afterEach(async () => {
    plannedResponses = {};
    sentRequests = [];
    openedUrls.length = 0;
    await useRouter().push('/');
    await clearSessionCache();
});

describe('the dashboard billing buttons', () => {
    it('B-50, B-33: Subscribe starts Checkout for the configured price and leaves for it', async () => {
        plannedResponses = {
            'POST /api/v1/billing/checkout': { status: 200, body: { data: { url: checkoutUrl } } },
        };
        await renderSuspended(App, { route: '/dashboard' });

        await pressButton('Subscribe');

        await waitFor(() => expect(openedUrls).toEqual([checkoutUrl]));
        const [checkoutRequest] = readSentRequests('POST /api/v1/billing/checkout');
        expect(await checkoutRequest!.json()).toEqual({ price_id: configuredPriceId });
        // The Idempotency-Key is asserted in tests/nuxt/api/createCheckoutSession.test.ts, in the
        // node environment: happy-dom drops every custom request header before a fetch stub sees it.
    });

    it('B-50, B-22: Manage billing opens the portal', async () => {
        plannedResponses = {
            'POST /api/v1/billing/portal': { status: 200, body: { data: { url: portalUrl } } },
        };
        await renderSuspended(App, { route: '/dashboard' });

        await pressButton('Manage billing');

        await waitFor(() => expect(openedUrls).toEqual([portalUrl]));
    });

    it('B-22: a user with no billing account is told so and stays on the dashboard', async () => {
        plannedResponses = {
            'POST /api/v1/billing/portal': {
                status: 400,
                body: {
                    code: 'BILLING_NO_ACCOUNT',
                    error: 'No billing account exists for this user',
                },
            },
        };
        await renderSuspended(App, { route: '/dashboard' });

        await pressButton('Manage billing');

        await waitFor(() =>
            expect(screen.queryByRole('alert')?.textContent ?? '').toContain(
                'No billing account exists',
            ),
        );
        expect(openedUrls).toEqual([]);
        expect(useRouter().currentRoute.value.path).toBe('/dashboard');
    });
});
