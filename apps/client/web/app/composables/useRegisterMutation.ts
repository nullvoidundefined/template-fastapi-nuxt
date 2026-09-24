/**
 * Registers and records the new session in the query cache (spec: B-10). Registration signs the
 * account in, so the cache is written exactly as a sign-in writes it.
 */
import { useMutation, useQueryClient } from '@tanstack/vue-query';

import { registerUser } from '~/api/registerUser';
import { useApiClient } from '~/composables/useApiClient';
import { sessionQueryKey } from '~/composables/useSessionQuery';
import type { CredentialsInput } from '~/types/credentialsInput';
import type { CurrentUser } from '~/types/currentUser';

/** Return the mutation the register form submits through. */
export function useRegisterMutation(): ReturnType<
    typeof useMutation<CurrentUser, Error, CredentialsInput>
> {
    const apiClient = useApiClient();
    const queryClient = useQueryClient();
    return useMutation<CurrentUser, Error, CredentialsInput>({
        mutationFn: (credentials) => registerUser(apiClient, credentials),
        onSuccess: (registeredUser) => {
            queryClient.setQueryData(sessionQueryKey, registeredUser);
        },
    });
}
