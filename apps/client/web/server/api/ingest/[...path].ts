/**
 * Proxies PostHog ingestion from `/api/ingest/<rest>` to `runtimeConfig.posthogHost` (spec: B-24,
 * the Nuxt track's Proxies section).
 *
 * The browser SDK sends to its own origin, so an ad blocker that drops requests to PostHog's
 * domain lets analytics through. Nitro ranks this route above the `/api/**` backend catch-all, so
 * nothing under `/api/ingest` ever reaches FastAPI.
 *
 * Three guards keep it from being anything but that. Only PostHog's ingest endpoints are
 * forwarded, so the origin is not a pass-through to PostHog's whole API. The target is built with
 * `new URL` and must land on the PostHog origin, because the request path arrives normalized (`..`
 * resolved) while the route matched the raw one, and a remainder beginning with `@` would
 * otherwise turn the host into userinfo and send the request anywhere. And the visitor's
 * credentials and forwarding headers are removed, since PostHog has no use for them.
 */
const INGEST_ROUTE_PREFIX = '/api/ingest';
const NOT_FOUND_STATUS = 404;
// The endpoints posthog-js calls: events, the batch and flag endpoints, and its static assets.
const INGEST_PATH_PATTERN =
    /^\/(?:e|i\/v0\/e|batch|flags|decide|static\/[\w.-]+|array\/[\w-]+\/config(?:\.js)?)\/?$/;
const WITHHELD_HEADER_NAMES = [
    'authorization',
    'cookie',
    'forwarded',
    'x-forwarded-for',
    'x-forwarded-host',
    'x-forwarded-proto',
    'x-real-ip',
    'x-request-id',
];

export default defineEventHandler(async (event) => {
    const { posthogHost } = useRuntimeConfig(event);
    const { pathname, search } = getRequestURL(event);
    const ingestPath = pathname.slice(INGEST_ROUTE_PREFIX.length);
    const target = buildIngestTarget(posthogHost, ingestPath, search);
    if (!target) {
        // Thrown rather than returned: an empty answer lets the router fall through to the
        // backend catch-all, which would forward the hostile path to FastAPI instead.
        throw createError({ statusCode: NOT_FOUND_STATUS, statusMessage: 'Not Found' });
    }
    const { headers } = event.node.req;
    for (const headerName of WITHHELD_HEADER_NAMES) {
        Reflect.deleteProperty(headers, headerName);
    }
    return proxyRequest(event, target);
});

/** Return the PostHog URL for an allowed ingest path, or undefined for anything else. */
function buildIngestTarget(
    posthogHost: string,
    ingestPath: string,
    search: string,
): string | undefined {
    if (!INGEST_PATH_PATTERN.test(ingestPath)) {
        return undefined;
    }
    const hostOrigin = new URL(posthogHost).origin;
    const target = new URL(`${ingestPath}${search}`, hostOrigin);
    return target.origin === hostOrigin ? target.toString() : undefined;
}
