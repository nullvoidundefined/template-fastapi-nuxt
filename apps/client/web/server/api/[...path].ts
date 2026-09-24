/**
 * Proxies `/api/<rest>` to the backend's `/<rest>` (spec: Architecture, "Request path").
 *
 * The browser only ever calls its own origin, so this route is the whole path from a page to
 * FastAPI. It exists as a route file rather than a `routeRules` proxy because a file is visible,
 * testable, and can do the one thing a rule cannot: rewrite the forwarded address before the
 * request leaves.
 *
 * Two details are load-bearing. The target carries the query string, because the catch-all's path
 * parameter excludes it and `proxyRequest` uses the target verbatim, so building the target from
 * the parameter alone silently drops `?page=2`. And `X-Forwarded-For` is replaced rather than
 * forwarded: h3 passes the header through untouched, every entry but the last is client-supplied,
 * and the backend's rate limiter keys on what arrives, so forwarding the chain would let one
 * client rotate buckets at will.
 */
import { resolveClientAddress } from '#shared/services/resolveClientAddress';

import { isForwardableBackendPath } from '../services/isForwardableBackendPath';

const NOT_FOUND_STATUS = 404;
// Headers a client can set to lie about where a request came from; the backend trusts them from
// Nitro, so none of them is forwarded as the client sent it.
const CLIENT_FORWARDING_HEADER_NAMES = new Set(['x-forwarded-for']);

export default defineEventHandler(async (event) => {
    const { apiBaseUrl } = useRuntimeConfig(event);
    const backendPath = getRouterParam(event, 'path') ?? '';
    // Only /v1 paths with no dot segment, encoded or not, are forwarded; see the guard.
    if (!isForwardableBackendPath(backendPath)) {
        throw createError({ statusCode: NOT_FOUND_STATUS, statusMessage: 'Not Found' });
    }
    const target = `${apiBaseUrl}/${backendPath}${getRequestURL(event).search}`;
    const forwardedAddressHeader = buildForwardedAddressHeader(event);
    stripClientForwardingHeaders(event);
    return proxyRequest(event, target, { headers: forwardedAddressHeader });
});

type ProxiedEvent = Parameters<typeof getRequestIP>[0];

/** Return the `X-Forwarded-For` override, or nothing to forward when no address is trustworthy. */
function buildForwardedAddressHeader(event: ProxiedEvent): Record<string, string> {
    const clientAddress = resolveClientAddress(
        getRequestHeader(event, 'x-forwarded-for'),
        getRequestIP(event),
    );
    return clientAddress ? { 'x-forwarded-for': clientAddress } : {};
}

/**
 * Remove the client's own forwarding headers from the inbound request before it is copied.
 *
 * `proxyRequest` always starts from every inbound header and can only add or overwrite, never
 * remove, so the inbound request's headers are replaced with a copy that leaves them out. The route is the last reader
 * of the request, so nothing downstream loses a header it needed.
 */
function stripClientForwardingHeaders(event: ProxiedEvent): void {
    const inboundRequest = event.node.req;
    inboundRequest.headers = Object.fromEntries(
        Object.entries(inboundRequest.headers).filter(
            ([headerName]) => !CLIENT_FORWARDING_HEADER_NAMES.has(headerName),
        ),
    );
}
