/**
 * The admin page's query over `GET /v1/admin/users` (spec: B-19). The key carries the paging, so
 * each page is cached on its own.
 */
import { useQuery } from '@tanstack/vue-query';

import { fetchAdminUsers } from '~/api/fetchAdminUsers';
import { useApiClient } from '~/composables/useApiClient';

export const ADMIN_USERS_PAGE_SIZE = 50;

/** Read the first page of users. */
export function useAdminUsersQuery(): ReturnType<
    typeof useQuery<Awaited<ReturnType<typeof fetchAdminUsers>>>
> {
    const apiClient = useApiClient();
    const paging = { limit: ADMIN_USERS_PAGE_SIZE, offset: 0 };
    return useQuery({
        queryFn: () => fetchAdminUsers(apiClient, paging),
        queryKey: ['admin-users', paging],
    });
}
