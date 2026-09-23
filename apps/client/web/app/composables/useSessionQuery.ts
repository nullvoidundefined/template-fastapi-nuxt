/**
 * The one query every signed-in surface reads the session through (spec: B-12, B-32).
 *
 * The composable owns the key, so the gate, the layout, and the sign-out mutation all refer to the
 * same cache entry without rebuilding it. The query cache is the only copy of the session: nothing
 * copies it into app state, because two copies of who is signed in drift.
 *
 * It revalidates on every mount rather than trusting a cached success. Without that, a session
 * that expired while a tab sat open would let the visitor navigate the whole protected area until
 * the entry went stale on its own, which is the opposite of what the gate is for. The cached value
 * is still shown while the revalidation runs, so a server-rendered page does not flash a loader.
 */
import { useQuery } from '@tanstack/vue-query';

import { fetchCurrentUser } from '~/api/fetchCurrentUser';
import { useApiClient } from '~/composables/useApiClient';

export const sessionQueryKey = ['session'];

/** Read the signed-in user, refetching on each mount so an expired session is caught. */
export function useSessionQuery(): ReturnType<
    typeof useQuery<Awaited<ReturnType<typeof fetchCurrentUser>>>
> {
    const apiClient = useApiClient();
    return useQuery({
        queryKey: sessionQueryKey,
        queryFn: () => fetchCurrentUser(apiClient),
        staleTime: 0,
        refetchOnMount: 'always',
    });
}
