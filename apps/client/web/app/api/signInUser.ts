/**
 * Starts a session through `POST /v1/auth/login` (spec: B-11).
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';
import type { CurrentUser } from '~/types/currentUser';
import type { CredentialsInput } from '~/types/credentialsInput';

/** Sign in and return the signed-in user, or throw an `ApiRequestError`. */
export async function signInUser(
    apiClient: ApiClient,
    credentials: CredentialsInput,
): Promise<CurrentUser> {
    const { data } = unwrapApiResponse(
        await apiClient.POST('/v1/auth/login', { body: credentials }),
    );
    return data;
}
