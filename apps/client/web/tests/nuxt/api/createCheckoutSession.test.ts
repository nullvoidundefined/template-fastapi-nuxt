// @vitest-environment node
/**
 * Tests for the `POST /v1/billing/checkout` wrapper (spec: B-33, B-17).
 *
 * Run in the node environment, as `signOutUser.test.ts` is, because happy-dom drops custom request
 * headers before a fetch stub can read them, and the header is the point: every press sends its
 * own `Idempotency-Key`, so a retry of one press replays and a second press starts a new session.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';

import { createApiClient } from '~/api/apiClient';
import { createCheckoutSession } from '~/api/createCheckoutSession';

const apiBaseUrl = 'http://api.test';
const checkoutUrl = 'https://checkout.stripe.test/c/pay/cs_test_1';

/** Stub fetch to record every request and answer with a Checkout URL. */
function stubCheckoutBackend(): Request[] {
    const sentRequests: Request[] = [];
    vi.stubGlobal('fetch', async (input: Parameters<typeof fetch>[0], init?: RequestInit) => {
        sentRequests.push(new Request(input, init));
        return new Response(JSON.stringify({ data: { url: checkoutUrl } }), {
            headers: { 'Content-Type': 'application/json' },
            status: 200,
        });
    });
    return sentRequests;
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('createCheckoutSession', () => {
    it('B-33: posts the price with a fresh Idempotency-Key on every call and returns the URL', async () => {
        const sentRequests = stubCheckoutBackend();
        const apiClient = createApiClient({ baseUrl: apiBaseUrl });

        const firstUrl = await createCheckoutSession(apiClient, 'price_template1');
        await createCheckoutSession(apiClient, 'price_template1');

        expect(firstUrl).toBe(checkoutUrl);
        const [firstKey, secondKey] = sentRequests.map((sent) =>
            sent.headers.get('Idempotency-Key'),
        );
        expect(firstKey).toMatch(/^[0-9a-f-]{36}$/);
        expect(secondKey).toMatch(/^[0-9a-f-]{36}$/);
        expect(secondKey).not.toBe(firstKey);
        expect(await sentRequests[0]!.json()).toEqual({ price_id: 'price_template1' });
    });
});
