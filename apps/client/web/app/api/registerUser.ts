/**
 * Creates an account through `POST /v1/auth/register` (spec: B-10), which also signs it in.
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';
import type { CurrentUser } from '~/types/currentUser';
import type { CredentialsInput } from '~/types/credentialsInput';

/** Register and return the new signed-in user, or throw an `ApiRequestError`. */
export async function registerUser(
    apiClient: ApiClient,
    credentials: CredentialsInput,
): Promise<CurrentUser> {
    const { data } = unwrapApiResponse(
        await apiClient.POST('/v1/auth/register', { body: credentials }),
    );
    return data;
}
