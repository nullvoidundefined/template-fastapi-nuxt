/**
 * Lists users through `GET /v1/admin/users` (spec: B-19). The backend answers 403
 * `AUTH_ADMIN_REQUIRED` to a member, so the page's own gate is a convenience, not the protection.
 */
import type { ApiClient } from '~/api/apiClient';
import { unwrapApiResponse } from '~/services/apiClient/unwrapApiResponse';
import type { AdminUserPage } from '~/types/adminUserPage';

/** Return one page of users, or throw an `ApiRequestError`. */
export async function fetchAdminUsers(
    apiClient: ApiClient,
    paging: { limit: number; offset: number },
): Promise<AdminUserPage> {
    return unwrapApiResponse(await apiClient.GET('/v1/admin/users', { params: { query: paging } }));
}
