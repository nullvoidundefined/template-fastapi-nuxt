/**
 * The one query every signed-in surface reads the session through (spec: B-12, B-32).
 *
 * The composable owns the key, so the gate, the layout, and the sign-out mutation all refer to the
 * same cache entry without rebuilding it. The query cache is the only copy of the session: nothing
 * copies it into app state, because two copies of who is signed in drift.
 *
 * It does not refetch on mount when the cache already holds an answer. Every navigation to a
 * protected page passes `require-session`, which revalidates the session into this same entry
 * just before the page mounts, so a mount-time refetch would ask the backend a second time for
 * the answer it has just given and spend the global rate-limit bucket doing it (IAN-335). An
 * expired session is still caught on the next navigation by the gate, and on window focus by the
 * zero stale time. A mount with nothing cached still fetches.
 */
import { useQuery } from '@tanstack/vue-query';

import { fetchCurrentUser } from '~/api/fetchCurrentUser';
import { useApiClient } from '~/composables/useApiClient';

export const sessionQueryKey = ['session'];

/** Read the signed-in user from the entry the gate revalidated for this navigation. */
export function useSessionQuery(): ReturnType<
    typeof useQuery<Awaited<ReturnType<typeof fetchCurrentUser>>>
> {
    const apiClient = useApiClient();
    return useQuery({
        queryFn: () => fetchCurrentUser(apiClient),
        queryKey: sessionQueryKey,
        refetchOnMount: false,
        staleTime: 0,
    });
}
