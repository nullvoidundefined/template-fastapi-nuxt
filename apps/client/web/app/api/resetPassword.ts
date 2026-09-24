/**
 * Sets a new password with the emailed token through `POST /v1/auth/reset-password` (spec: B-15).
 * Success signs out every session, so the caller sends the visitor to sign in again.
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';
import type { PasswordResetInput } from '~/types/passwordResetInput';

/** Reset the password, or throw an `ApiRequestError` for a used, expired or unknown token. */
export async function resetPassword(
    apiClient: ApiClient,
    passwordReset: PasswordResetInput,
): Promise<void> {
    unwrapApiResponse(await apiClient.POST('/v1/auth/reset-password', { body: passwordReset }));
}
