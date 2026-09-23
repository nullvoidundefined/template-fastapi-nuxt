/**
 * Tests for the protected layout (spec: slice 03 PR 3, B-12, US-AUTH-003).
 *
 * The layout is the third part of the gate. The Nitro middleware checks a cookie is present, the
 * route middleware asks the backend whether it is still valid, and this layout makes sure nothing
 * behind the gate is painted before that answer arrives. Without it a protected page renders its
 * content in the gap between mount and the session response, and a visitor whose session has
 * expired sees the dashboard for a moment before being redirected.
 *
 * The slot content here is supplied by the test rather than by a real page, so the assertions are
 * about what a page put behind this layout would show, queried by role and accessible name.
 *
 * The three tests together are what make the file non-vacuous: a layout that never rendered its
 * slot at all would pass the first and third and fail the second. The absence assertions are made
 * at a moment the test controls rather than on the first tick, the first while the backend answer
 * is held open and the last once the session query has actually settled into its error state, so
 * neither one can pass merely because nothing has happened yet.
 */
import { describe, it, expect, afterEach, beforeAll, vi } from 'vitest';
import { h } from 'vue';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen } from '@testing-library/vue';

import ProtectedLayout from '~/layouts/protected.vue';
import { sessionQueryKey } from '~/composables/useSessionQuery';

import {
    clearSessionCache,
    holdBackendResponse,
    installBackendStub,
    planExpiredSession,
    planSignedInSession,
    readAppQueryClient,
    readSentRequests,
    releaseBackendResponse,
} from '../middleware/sessionGateHarness';

const protectedHeading = 'Account settings';

/** Render the layout with one heading behind it, standing in for a protected page's content. */
async function renderProtectedLayout(): Promise<void> {
    await renderSuspended(ProtectedLayout, {
        slots: { default: () => h('h1', protectedHeading) },
    });
}

/** Wait until the session query has reached the given status, so absence is asserted in earnest. */
async function waitForSessionStatus(expectedStatus: 'error' | 'success'): Promise<void> {
    const queryClient = await readAppQueryClient();
    await vi.waitFor(() => {
        expect(queryClient.getQueryState(sessionQueryKey)?.status).toBe(expectedStatus);
    });
}

beforeAll(() => {
    installBackendStub();
});

afterEach(async () => {
    releaseBackendResponse();
    await clearSessionCache();
});

describe('the protected layout', () => {
    it('B-12: paints nothing behind the gate while the session is still unresolved', async () => {
        planSignedInSession();
        holdBackendResponse();

        await renderProtectedLayout();

        expect(readSentRequests()).not.toHaveLength(0);
        expect(screen.queryByRole('heading', { name: protectedHeading })).toBeNull();
    });

    it('B-12: renders the page once the session resolves', async () => {
        planSignedInSession();
        holdBackendResponse();
        await renderProtectedLayout();

        releaseBackendResponse();

        await vi.waitFor(() => {
            expect(screen.queryByRole('heading', { name: protectedHeading })).not.toBeNull();
        });
    });

    it('B-12: paints nothing behind the gate when the backend rejects the session', async () => {
        planExpiredSession();

        await renderProtectedLayout();
        await waitForSessionStatus('error');

        expect(screen.queryByRole('heading', { name: protectedHeading })).toBeNull();
    });
});
