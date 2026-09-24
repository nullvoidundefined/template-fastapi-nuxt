/**
 * Sends a signed-in visitor away from the signed-out pages (spec: B-45).
 *
 * It does not look at which page it is guarding, so `/login` and `/register` cannot drift apart:
 * a redirect applied to one and forgotten on the other is the mistake this shape rules out.
 *
 * Anything other than a confirmed session leaves the visitor where they are. Someone whose session
 * has expired belongs on the sign-in page, and so does someone the backend cannot answer for:
 * refusing to show a sign-in page because the API is down would strand the one person who could
 * do nothing about it.
 */
import { defineNuxtRouteMiddleware, navigateTo } from '#imports';
import { useQueryClient } from '@tanstack/vue-query';

import { useApiClient } from '~/composables/useApiClient';
import { readSessionOutcome } from '~/services/session/readSessionOutcome';

const DASHBOARD_PATH = '/dashboard';

export default defineNuxtRouteMiddleware(async () => {
    const queryClient = useQueryClient();
    const apiClient = useApiClient();
    const outcome = await readSessionOutcome(queryClient, apiClient);
    if (outcome.state === 'signedIn') {
        return navigateTo(DASHBOARD_PATH);
    }
    return undefined;
});
