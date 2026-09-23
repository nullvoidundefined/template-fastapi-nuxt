/**
 * Changes the signed-in user's password through `PATCH /v1/auth/me` (spec: B-13, B-50). The
 * backend signs out every other session and keeps this one.
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';
import type { CurrentUser } from '~/types/currentUser';
import type { PasswordChangeInput } from '~/types/passwordChangeInput';

/** Change the password and return the user, or throw an `ApiRequestError`. */
export async function changePassword(
    apiClient: ApiClient,
    passwordChange: PasswordChangeInput,
): Promise<CurrentUser> {
    const { data } = unwrapApiResponse(
        await apiClient.PATCH('/v1/auth/me', { body: passwordChange }),
    );
    return data;
}
