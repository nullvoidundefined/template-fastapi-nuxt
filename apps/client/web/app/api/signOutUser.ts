/**
 * Ends the current session through `POST /v1/auth/logout` (spec: B-31).
 *
 * The route answers 204 whether or not a session existed, so a resolved call means the cookie is
 * cleared either way. A refusal still throws, and the caller keeps the cached session rather than
 * showing a signed-out page the backend does not agree with.
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';

/** End the session, or throw an `ApiRequestError` when the backend refuses. */
export async function signOutUser(apiClient: ApiClient): Promise<void> {
    unwrapApiResponse(await apiClient.POST('/v1/auth/logout'));
}
