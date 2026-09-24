/**
 * Keeps a signed-out visitor off a protected page (spec: B-12).
 *
 * This is the half of the gate that covers client-side navigation, which never reaches the Nitro
 * middleware, and the expired cookie the Nitro middleware let through because it checks only that
 * a cookie is present.
 *
 * An unreachable backend aborts the navigation with its error rather than redirecting. Redirecting
 * would sign the visitor out because the API is down, which is both wrong and quiet.
 */
import {
    abortNavigation,
    createError,
    defineNuxtRouteMiddleware,
    navigateTo,
    useNuxtApp,
} from '#imports';
import { useQueryClient } from '@tanstack/vue-query';

import { useApiClient } from '~/composables/useApiClient';
import { hasRecentServerSession } from '~/services/session/hasRecentServerSession';
import { isHydratingServerRender } from '~/services/session/isHydratingServerRender';
import { readSessionOutcome } from '~/services/session/readSessionOutcome';

const LOGIN_PATH = '/login';
const SESSION_UNAVAILABLE_MESSAGE = 'The session could not be confirmed';

export default defineNuxtRouteMiddleware(async () => {
    const queryClient = useQueryClient();
    // The server already ran this gate for the page being hydrated, so asking again spends a
    // request; but only a session the server fetched just now proves that, since a render
    // replayed from the HTTP cache carries an old one that may have been revoked (IAN-335).
    if (isHydratingServerRender(useNuxtApp()) && hasRecentServerSession(queryClient)) {
        return undefined;
    }
    const apiClient = useApiClient();
    const outcome = await readSessionOutcome(queryClient, apiClient);
    if (outcome.state === 'signedIn') {
        return undefined;
    }
    if (outcome.state === 'signedOut') {
        return navigateTo(LOGIN_PATH);
    }
    const { status } = outcome;
    return abortNavigation(
        createError({ statusCode: status, statusMessage: SESSION_UNAVAILABLE_MESSAGE }),
    );
});
