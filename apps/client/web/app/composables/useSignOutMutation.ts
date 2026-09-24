/**
 * Ends the session and forgets it locally (spec: B-31).
 *
 * `onSuccess` removes the session entry rather than invalidating it. Invalidating would refetch
 * `GET /v1/auth/me` with a cookie that has just been cleared, so the visitor would be signed out
 * and simultaneously watching a request fail; removing leaves the gate with no session, which is
 * exactly what has just become true.
 *
 * A successful sign-out also resets PostHog's identified user (B-24), so the next visitor on this
 * browser is not recorded as the last one.
 *
 * A refused sign-out removes nothing, so the page does not claim a signed-out state the backend
 * does not agree with.
 */
import { useMutation, useQueryClient } from '@tanstack/vue-query';

import { signOutUser } from '~/api/signOutUser';
import { resetAnalyticsUser } from '~/clients/analytics';
import { useApiClient } from '~/composables/useApiClient';
import { sessionQueryKey } from '~/composables/useSessionQuery';

/** Return the mutation a sign-out control calls, which forgets the session on success. */
export function useSignOutMutation(): ReturnType<typeof useMutation<undefined, Error, undefined>> {
    const apiClient = useApiClient();
    const queryClient = useQueryClient();
    return useMutation<undefined, Error, undefined>({
        mutationFn: async () => {
            await signOutUser(apiClient);
            return undefined;
        },
        onSuccess: () => {
            queryClient.removeQueries({ exact: true, queryKey: sessionQueryKey });
            resetAnalyticsUser();
        },
    });
}
