/**
 * End-to-end checks of the API health endpoints and request-ID header against a running API.
 * Stories US-INFRA-001 (spec B-1) and US-INFRA-002 (spec B-2); the base URL comes from API_BASE_URL.
 */
import { test, expect } from '@playwright/test';

const apiBaseUrl = process.env.API_BASE_URL ?? '';

test.describe('API health endpoints', () => {
    test('US-INFRA-001: GET /health answers 200 with status ok (B-1)', async ({ request }) => {
        const response = await request.get(`${apiBaseUrl}/health`);

        expect(response.status()).toBe(200);
        expect(await response.json()).toEqual({ status: 'ok' });
    });

    test('US-INFRA-001: GET /health/ready answers 200 with the database connected (B-1)', async ({
        request,
    }) => {
        const response = await request.get(`${apiBaseUrl}/health/ready`);

        expect(response.status()).toBe(200);
        expect(await response.json()).toEqual({ status: 'ok', db: 'connected' });
    });

    test('US-INFRA-002: a valid inbound X-Request-Id is echoed on the response (B-2)', async ({
        request,
    }) => {
        const inboundRequestId = 'e2e-health.check_1';

        const response = await request.get(`${apiBaseUrl}/health`, {
            headers: { 'X-Request-Id': inboundRequestId },
        });

        expect(response.status()).toBe(200);
        expect(response.headers()['x-request-id']).toBe(inboundRequestId);
    });

    test('US-INFRA-002: a response without an inbound ID carries a new UUID (B-2)', async ({
        request,
    }) => {
        const uuidPattern = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;

        const response = await request.get(`${apiBaseUrl}/health/ready`);

        expect(response.status()).toBe(200);
        expect(response.headers()['x-request-id']).toMatch(uuidPattern);
    });
});
