/**
 * Signs in and records the session in the query cache (spec: B-11).
 *
 * `onSuccess` writes the returned user into the session entry, so the dashboard's gate finds a
 * session without a second round trip; the gate still revalidates on navigation.
 */
import { useMutation, useQueryClient } from '@tanstack/vue-query';

import { signInUser } from '~/api/signInUser';
import { useApiClient } from '~/composables/useApiClient';
import { sessionQueryKey } from '~/composables/useSessionQuery';
import type { CredentialsInput } from '~/types/credentialsInput';
import type { CurrentUser } from '~/types/currentUser';

/** Return the mutation the sign-in form submits through. */
export function useSignInMutation(): ReturnType<
    typeof useMutation<CurrentUser, Error, CredentialsInput>
> {
    const apiClient = useApiClient();
    const queryClient = useQueryClient();
    return useMutation<CurrentUser, Error, CredentialsInput>({
        mutationFn: (credentials) => signInUser(apiClient, credentials),
        onSuccess: (signedInUser) => {
            queryClient.setQueryData(sessionQueryKey, signedInUser);
        },
    });
}
