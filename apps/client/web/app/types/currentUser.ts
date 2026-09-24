/** The signed-in user as every surface reads it: what the backend returns from `GET /v1/auth/me`. */
import type { components } from '@repo/api-types';

export type CurrentUser = components['schemas']['AuthenticatedUserData'];
