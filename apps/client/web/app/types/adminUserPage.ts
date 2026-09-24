/** One page of `GET /v1/admin/users`: the users and the paging it was cut from. */
import type { components } from '@repo/api-types';

export type AdminUserPage = components['schemas']['AdminUserListResponse'];
