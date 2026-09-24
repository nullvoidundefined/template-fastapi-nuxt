/**
 * Keeps a member off an admin page (spec: B-19). It runs after `require-session`, which has just
 * revalidated the session into the cache, so it reads the role from there rather than asking again.
 * A member goes to the dashboard, the page they can use; the backend refuses them regardless.
 */
import { defineNuxtRouteMiddleware, navigateTo } from '#imports';
import { useQueryClient } from '@tanstack/vue-query';

import { sessionQueryKey } from '~/composables/useSessionQuery';
import type { CurrentUser } from '~/types/currentUser';

const MEMBER_HOME_PATH = '/dashboard';
const ADMIN_ROLE = 'admin';

export default defineNuxtRouteMiddleware(() => {
    const signedInUser = useQueryClient().getQueryData<CurrentUser>(sessionQueryKey);
    if (signedInUser && signedInUser.role !== ADMIN_ROLE) {
        return navigateTo(MEMBER_HOME_PATH);
    }
    return undefined;
});
