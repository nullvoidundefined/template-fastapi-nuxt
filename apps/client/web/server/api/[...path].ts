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
 * the parameter alone silently drops `?page=2`. And the client's forwarding headers are never
 * forwarded as sent: h3 passes every inbound header through untouched, while uvicorn trusts
 * `X-Forwarded-For`, `X-Forwarded-Proto`, and their kin from Nitro's address. `X-Forwarded-For` is
 * replaced with the one trustworthy entry, or dropped when none resolves, because every entry but
 * the last is client-supplied and the backend's rate limiter keys on what arrives, so forwarding
 * the chain would let one client rotate buckets at will. Every other forwarding header in the
 * shared list is dropped, so a client cannot claim an address, scheme, host, port, or prefix it
 * did not use.
 *
 * The headers are deleted from the inbound request itself, because `proxyRequest` can only add or
 * overwrite. Anything that reads the request afterwards, Sentry's error handler included, sees it
 * without them, which loses nothing: they were the client's claims, not facts about the request.
 */
import { resolveClientAddress } from '#shared/services/resolveClientAddress';

import { isForwardableBackendPath } from '../services/isForwardableBackendPath';
import {
    CLIENT_FORWARDING_HEADER_NAMES,
    withholdRequestHeaders,
} from '../services/withholdRequestHeaders';

const NOT_FOUND_STATUS = 404;

export default defineEventHandler(async (event) => {
    const { apiBaseUrl } = useRuntimeConfig(event);
    const backendPath = getRouterParam(event, 'path') ?? '';
    // Only /v1 paths with no dot segment, encoded or not, are forwarded; see the guard.
    if (!isForwardableBackendPath(backendPath)) {
        throw createError({ statusCode: NOT_FOUND_STATUS, statusMessage: 'Not Found' });
    }
    const target = `${apiBaseUrl}/${backendPath}${getRequestURL(event).search}`;
    // Resolved before the chain is withheld, since the trusted entry is read from it.
    const forwardedAddressHeader = buildForwardedAddressHeader(event);
    withholdRequestHeaders(event, CLIENT_FORWARDING_HEADER_NAMES);
    return proxyRequest(event, target, { headers: forwardedAddressHeader });
});

/** Return the `X-Forwarded-For` override, or nothing to forward when no address is trustworthy. */
function buildForwardedAddressHeader(
    event: Parameters<typeof getRequestIP>[0],
): Record<string, string> {
    const clientAddress = resolveClientAddress(
        getRequestHeader(event, 'x-forwarded-for'),
        getRequestIP(event),
    );
    return clientAddress ? { 'x-forwarded-for': clientAddress } : {};
}
