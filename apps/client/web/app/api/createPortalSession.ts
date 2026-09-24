/**
 * Opens a Stripe billing portal session through `POST /v1/billing/portal` (spec: B-22).
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';

/** Return the portal URL, or throw an `ApiRequestError` (400 when there is no billing account). */
export async function createPortalSession(apiClient: ApiClient): Promise<string> {
    const { data } = unwrapApiResponse(await apiClient.POST('/v1/billing/portal'));
    return data.url;
}
