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

export default defineEventHandler(async (event) => {
    const { apiBaseUrl } = useRuntimeConfig(event);
    const backendPath = getRouterParam(event, 'path') ?? '';
    const target = `${apiBaseUrl}/${backendPath}${getRequestURL(event).search}`;
    return proxyRequest(event, target, {
        headers: buildForwardedAddressHeader(event),
    });
});

/** Return the `X-Forwarded-For` override, or nothing to forward when no address is trustworthy. */
function buildForwardedAddressHeader(event: Parameters<typeof getRequestIP>[0]) {
    const clientAddress = resolveClientAddress(
        getRequestHeader(event, 'x-forwarded-for'),
        getRequestIP(event),
    );
    return clientAddress ? { 'x-forwarded-for': clientAddress } : {};
}
