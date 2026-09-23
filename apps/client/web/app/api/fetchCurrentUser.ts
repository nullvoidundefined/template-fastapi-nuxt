/**
 * Reads the signed-in user from `GET /v1/auth/me` (spec: B-32).
 *
 * The client is a parameter rather than something this module obtains, because `useApiClient()`
 * resolves the Nuxt app instance and must run in setup; an `api/` function is called from a query
 * function, which runs after an await has already dropped that context.
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';
import type { CurrentUser } from '~/types/currentUser';

/** Return the signed-in user, or throw an `ApiRequestError` carrying the status and code. */
export async function fetchCurrentUser(apiClient: ApiClient): Promise<CurrentUser> {
    const envelope = unwrapApiResponse(await apiClient.GET('/v1/auth/me'));
    return envelope.data;
}
