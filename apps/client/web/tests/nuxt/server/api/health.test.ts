/**
 * Unit test for the Nitro route GET /api/health (story US-INFRA-003).
 * The web container's health check must answer { status: 'ok' } from the Nuxt server alone, so
 * the real handler is invoked with a minimal H3-shaped event while every outbound fetch throws.
 * The route is imported directly because the Vitest config runs the nuxt client environment,
 * which @nuxt/test-utils does not support for setup({ server: true }). The status code is not
 * asserted here, because a fresh ServerResponse already defaults to 200 and that check could not
 * fail; e2e/landing.spec.ts asserts the status and the body over HTTP.
 */
import { IncomingMessage, ServerResponse } from 'node:http';
import { Socket } from 'node:net';
import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

type HealthHandler = (event: unknown) => unknown;

function createHealthEvent() {
    const request = new IncomingMessage(new Socket());
    request.method = 'GET';
    request.url = '/api/health';
    const response = new ServerResponse(request);

    return {
        node: { req: request, res: response },
        path: '/api/health',
        method: 'GET',
        context: {},
    };
}

function throwOutboundRequest(): never {
    throw new Error('US-INFRA-003: /api/health must not make an outbound request');
}

let healthHandler: HealthHandler;

beforeAll(async () => {
    vi.stubGlobal('defineEventHandler', (handler: HealthHandler) => handler);
    vi.stubGlobal('fetch', throwOutboundRequest);
    vi.stubGlobal('$fetch', throwOutboundRequest);
    const healthRouteModule = await import('../../../../server/api/health.get');
    healthHandler = healthRouteModule.default as HealthHandler;
});

afterAll(() => {
    vi.unstubAllGlobals();
});

describe('GET /api/health', () => {
    it('US-INFRA-003: answers { status: "ok" } without contacting the backend', async () => {
        const healthEvent = createHealthEvent();

        const responseBody = await healthHandler(healthEvent);

        expect(responseBody).toEqual({ status: 'ok' });
    });
});
