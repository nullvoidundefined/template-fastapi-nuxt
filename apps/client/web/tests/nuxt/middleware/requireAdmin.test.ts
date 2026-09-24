/**
 * Tests for the admin gate's own decision (spec: B-19, US-ADMIN-001, IAN-339).
 *
 * `require-admin` reads the role from the session cache that `require-session` has just filled, so
 * these tests seed or empty that cache and call the middleware directly. The case that matters is
 * the empty cache: the gate cannot see a role, and it must send the visitor away rather than let
 * the admin page render. The backend's 403 still protects the data; this keeps the page shell and
 * its request from ever starting for someone who is not known to be an admin.
 */
import { describe, it, expect, afterEach, beforeAll } from 'vitest';

import requireAdmin from '~/middleware/requireAdmin';

import {
    clearSessionCache,
    installBackendStub,
    readRedirectPath,
    runRouteGate,
    seedCachedSession,
    signedInUser,
} from './sessionGateHarness';

const adminPath = '/admin';
const memberHomePath = '/dashboard';

beforeAll(() => {
    installBackendStub();
});

afterEach(async () => {
    await clearSessionCache();
});

describe('requireAdmin', () => {
    it('B-19: lets a cached admin through', async () => {
        await seedCachedSession({ ...signedInUser, role: 'admin' } as typeof signedInUser);

        const outcome = await runRouteGate(requireAdmin, adminPath);

        expect(outcome).toEqual({ settled: 'returned', value: undefined });
    });

    it('B-19: sends a cached member to the dashboard', async () => {
        await seedCachedSession({ ...signedInUser, role: 'member' } as typeof signedInUser);

        const outcome = await runRouteGate(requireAdmin, adminPath);

        expect(readRedirectPath(outcome)).toBe(memberHomePath);
    });

    it('IAN-339: fails closed and sends the visitor to the dashboard when the cache is empty', async () => {
        const outcome = await runRouteGate(requireAdmin, adminPath);

        expect(readRedirectPath(outcome)).toBe(memberHomePath);
    });
});
