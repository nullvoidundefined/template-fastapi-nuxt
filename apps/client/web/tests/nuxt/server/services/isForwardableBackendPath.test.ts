// @vitest-environment node
/**
 * Tests for the backend proxy's path guard (IAN-337 review, US-AUTH-003).
 *
 * The guard is tested on raw path strings because that is what a real Node server hands the
 * route: `getRouterParam` returns the path as sent, percent-encoding included, and only `fetch`
 * later resolves `%2e%2e` into `..`. A test driven through `new Request(url)` never sees an encoded
 * dot segment, because the URL parser has already resolved it.
 */
import { describe, it, expect } from 'vitest';

import { isForwardableBackendPath } from '../../../../server/services/isForwardableBackendPath';

describe('isForwardableBackendPath', () => {
    it.each(['v1/auth/me', 'v1/trips', 'v1/admin/users'])('forwards %s', (backendPath) => {
        expect(isForwardableBackendPath(backendPath)).toBe(true);
    });

    it.each([
        'v1/%2e%2e/openapi.json',
        'v1/%2E%2e/%2e%2E/docs',
        'v1/%2e/../health/ready',
        'v1/../health',
        'v1/trips/%2e%2e%2f%2e%2e/docs',
        'v1%2f..%2fdocs',
        'openapi.json',
        'health/ready',
    ])('refuses %s, which is not a /v1 path once fetch resolves it', (backendPath) => {
        expect(isForwardableBackendPath(backendPath)).toBe(false);
    });
});
