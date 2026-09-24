/**
 * Starts a Stripe Checkout session through `POST /v1/billing/checkout` (spec: B-33).
 *
 * Each call sends a fresh `Idempotency-Key`, so a double click or a network retry of one press
 * creates one Checkout session rather than two (the backend's idempotency middleware, B-17).
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';

/** Return the Checkout URL for the price, or throw an `ApiRequestError`. */
export async function createCheckoutSession(
    apiClient: ApiClient,
    priceId: string,
): Promise<string> {
    const { data } = unwrapApiResponse(
        await apiClient.POST('/v1/billing/checkout', {
            body: { price_id: priceId },
            headers: { 'Idempotency-Key': crypto.randomUUID() },
        }),
    );
    return data.url;
}
