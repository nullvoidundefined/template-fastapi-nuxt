// @vitest-environment node
/**
 * Unit tests for SSR options (spec: Architecture, "Request path" and "Client IP trust chain").
 * Server calls use an absolute backend URL and forward only the three permitted headers.
 */
import { describe, it, expect } from 'vitest';

const apiBaseUrl = 'http://api.test';

describe('buildServerApiClientOptions', () => {
    it('Request path: forwards only the cookie, request ID, and resolved client address', async () => {
        const { buildServerApiClientOptions } =
            await import('~/services/apiClient/buildServerApiClientOptions');

        expect(
            buildServerApiClientOptions({
                apiBaseUrl,
                requestHeaders: {
                    cookie: 'session=abc',
                    'x-request-id': 'req-page-001',
                    'x-forwarded-for': '1.1.1.1, 2.2.2.2, 203.0.113.7',
                    authorization: 'untrusted-value',
                    host: 'page.test',
                },
                socketAddress: '192.0.2.9',
            }),
        ).toEqual({
            baseUrl: apiBaseUrl,
            headers: {
                cookie: 'session=abc',
                'X-Request-Id': 'req-page-001',
                'X-Forwarded-For': '203.0.113.7',
            },
        });
    });

    it('Request path: omits absent sources and unrelated incoming headers', async () => {
        const { buildServerApiClientOptions } =
            await import('~/services/apiClient/buildServerApiClientOptions');

        expect(
            buildServerApiClientOptions({
                apiBaseUrl,
                requestHeaders: { authorization: 'untrusted-value', host: 'page.test' },
            }),
        ).toEqual({ baseUrl: apiBaseUrl, headers: {} });
    });

    it.each([undefined, '203.0.113.7, not-an-ip'])(
        'Client IP trust chain: forwards the socket fallback for %s',
        async (forwardedFor) => {
            const { buildServerApiClientOptions } =
                await import('~/services/apiClient/buildServerApiClientOptions');

            expect(
                buildServerApiClientOptions({
                    apiBaseUrl,
                    requestHeaders: { 'x-forwarded-for': forwardedFor },
                    socketAddress: '2001:db8::9',
                }),
            ).toEqual({
                baseUrl: apiBaseUrl,
                headers: { 'X-Forwarded-For': '2001:db8::9' },
            });
        },
    );

    it('Client IP trust chain: omits the forwarded header when neither source is valid', async () => {
        const { buildServerApiClientOptions } =
            await import('~/services/apiClient/buildServerApiClientOptions');

        expect(
            buildServerApiClientOptions({
                apiBaseUrl,
                requestHeaders: { 'x-forwarded-for': '203.0.113.7, not-an-ip' },
                socketAddress: 'invalid-peer',
            }),
        ).toEqual({ baseUrl: apiBaseUrl, headers: {} });
    });

    it.each(['http://api.test', 'https://api.test'])(
        'Request path: accepts the absolute backend URL %s',
        async (baseUrl) => {
            const { buildServerApiClientOptions } =
                await import('~/services/apiClient/buildServerApiClientOptions');

            expect(
                buildServerApiClientOptions({
                    apiBaseUrl: baseUrl,
                    requestHeaders: {},
                }),
            ).toEqual({ baseUrl, headers: {} });
        },
    );

    it.each(['', '/api', 'api.test', '//api.test', 'ftp://api.test', 'http://'])(
        'Request path: rejects an unusable server base URL %j',
        async (baseUrl) => {
            const { buildServerApiClientOptions } =
                await import('~/services/apiClient/buildServerApiClientOptions');

            expect(() =>
                buildServerApiClientOptions({
                    apiBaseUrl: baseUrl,
                    requestHeaders: {},
                }),
            ).toThrow();
        },
    );
});
