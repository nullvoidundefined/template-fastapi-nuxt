/**
 * Removes named headers from an inbound request before a proxy copies it (IAN-335, US-AUTH-003,
 * B-24).
 *
 * h3's `proxyRequest` starts from every inbound header and can only add or overwrite, so a header
 * that must not travel upstream is deleted from the inbound request itself. Both Nitro proxies
 * withhold the client's forwarding headers: the backend proxy because uvicorn trusts them from
 * Nitro's address, and the PostHog proxy because PostHog has no use for them. One list keeps the
 * two from drifting apart when a new forwarding header needs adding.
 */
import type { H3Event } from 'h3';

// Headers a client can set to claim an address, scheme, host, port, or path prefix it did not use.
export const CLIENT_FORWARDING_HEADER_NAMES = [
    'forwarded',
    'x-forwarded-for',
    'x-forwarded-host',
    'x-forwarded-port',
    'x-forwarded-prefix',
    'x-forwarded-proto',
    'x-real-ip',
];

/** Delete each named header from the inbound request, in place. */
export function withholdRequestHeaders(event: H3Event, headerNames: readonly string[]): void {
    const { headers } = event.node.req;
    for (const headerName of headerNames) {
        Reflect.deleteProperty(headers, headerName);
    }
}
