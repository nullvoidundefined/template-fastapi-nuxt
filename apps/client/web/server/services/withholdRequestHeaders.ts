/**
 * Removes named headers from an inbound request before a proxy copies it (IAN-335, US-AUTH-003,
 * B-24).
 *
 * h3's `proxyRequest` starts from every inbound header and can only add or overwrite, so a header
 * that must not travel upstream is deleted from the inbound request itself. Both Nitro proxies
 * call this with `CLIENT_FORWARDING_HEADER_NAMES`, the PostHog proxy adding the visitor's
 * credentials on top.
 */
import type { H3Event } from 'h3';

/** Delete each named header from the inbound request, in place. */
export function withholdRequestHeaders(event: H3Event, headerNames: readonly string[]): void {
    const { headers } = event.node.req;
    for (const headerName of headerNames) {
        Reflect.deleteProperty(headers, headerName);
    }
}
