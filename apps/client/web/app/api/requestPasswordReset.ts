/**
 * Asks for a reset email through `POST /v1/auth/forgot-password` (spec: B-14). The backend answers
 * 200 whether or not the address has an account, so a resolved call says nothing about that.
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';

/** Request the reset email, or throw an `ApiRequestError` when the backend refuses. */
export async function requestPasswordReset(apiClient: ApiClient, email: string): Promise<void> {
    unwrapApiResponse(await apiClient.POST('/v1/auth/forgot-password', { body: { email } }));
}
