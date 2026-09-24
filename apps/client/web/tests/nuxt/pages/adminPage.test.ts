/**
 * Tests for the admin page and its gate (spec: B-19, US-ADMIN-001).
 *
 * The application is rendered with the real router, both route middlewares, and the real API
 * client; only `fetch` is stubbed, answering by method and path from a plan each test sets. The
 * member case is asserted through a real navigation, because a page that renders correctly and
 * forgot its `require-admin` middleware would pass any assertion about what it draws.
 */
import { describe, it, expect, afterEach, beforeAll, vi } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen, waitFor } from '@testing-library/vue';
import { useRouter } from '#app';

import App from '~/app.vue';

import { clearSessionCache } from '../middleware/sessionGateHarness';

type PlannedResponse = { status: number; body?: unknown };

const adminUser = {
    id: '5b1f0c2e-8f3a-4c1d-9e2b-7a6d5c4b3a21',
    email: 'admin@example.test',
    role: 'admin',
};
const memberUser = {
    id: '9c2e1d3f-4a5b-4c6d-8e7f-1a2b3c4d5e6f',
    email: 'member@example.test',
    role: 'member',
};
const listedUsers = [
    { ...adminUser, created_at: '2026-09-01T10:00:00Z' },
    { ...memberUser, created_at: '2026-09-02T11:30:00Z' },
];

let plannedResponses: Record<string, PlannedResponse> = {};
let sentRequests: Request[] = [];

/** Answer from the plan keyed by `METHOD /path`, or 401 for anything unplanned. */
async function answerByRoute(
    input: Parameters<typeof fetch>[0],
    init?: RequestInit,
): Promise<Response> {
    const sentRequest = new Request(input, init);
    sentRequests.push(sentRequest);
    const routeKey = `${sentRequest.method} ${new URL(sentRequest.url).pathname}`;
    const { status, body } = plannedResponses[routeKey] ?? {
        status: 401,
        body: { code: 'AUTH_REQUIRED', error: 'Sign in to continue.' },
    };
    return new Response(body === undefined ? null : JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

/** Plan the session as this user, and the admin list as the backend would answer it. */
function planSignedInAs(user: typeof adminUser): void {
    plannedResponses = {
        'GET /api/v1/auth/me': { status: 200, body: { data: user } },
        'GET /api/v1/admin/users': {
            status: 200,
            body: { data: listedUsers, meta: { limit: 50, offset: 0, total: 2 } },
        },
    };
    sentRequests = [];
}

beforeAll(() => {
    vi.stubGlobal('fetch', answerByRoute);
});

afterEach(async () => {
    plannedResponses = {};
    await useRouter().push('/');
    await clearSessionCache();
});

describe('the admin page', () => {
    it('B-19: an admin sees every user with their role and join date', async () => {
        planSignedInAs(adminUser);

        await renderSuspended(App, { route: '/admin' });

        await waitFor(() => expect(screen.queryAllByRole('row')).toHaveLength(3));
        expect(screen.queryByRole('heading', { level: 1 })?.textContent).toContain('Users');
        const [, adminRow, memberRow] = screen.queryAllByRole('row');
        expect(adminRow?.textContent).toContain(adminUser.email);
        expect(adminRow?.textContent).toContain('admin');
        expect(memberRow?.textContent).toContain(memberUser.email);
        expect(memberRow?.textContent).toContain('member');
        expect(screen.queryByText(/Showing 2 of 2/)).not.toBeNull();
    });

    it('B-19: a member navigating to /admin lands on the dashboard', async () => {
        planSignedInAs(memberUser);

        await useRouter().push('/admin');

        expect(useRouter().currentRoute.value.path).toBe('/dashboard');
        const adminListCalls = sentRequests.filter(
            (sentRequest) => new URL(sentRequest.url).pathname === '/api/v1/admin/users',
        );
        expect(adminListCalls).toHaveLength(0);
    });

    it('B-19: a signed-out visitor navigating to /admin lands on the sign-in page', async () => {
        plannedResponses = {};

        await useRouter().push('/admin');

        expect(useRouter().currentRoute.value.path).toBe('/login');
    });
});
