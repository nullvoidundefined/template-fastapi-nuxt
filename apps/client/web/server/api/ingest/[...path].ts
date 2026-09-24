/**
 * Proxies PostHog ingestion from `/api/ingest/<rest>` to `runtimeConfig.posthogHost` (spec: B-24,
 * the Nuxt track's Proxies section).
 *
 * The browser SDK sends to its own origin, so an ad blocker that drops requests to PostHog's
 * domain lets analytics through. Nitro ranks this route above the `/api/**` backend catch-all, so
 * nothing under `/api/ingest` ever reaches FastAPI.
 *
 * The session cookie is removed before the request is forwarded. PostHog has no use for it, and
 * h3 forwards every request header by default, so without this the proxy would hand a third party
 * the credential of every signed-in visitor. The target is built from the request URL rather than
 * the catch-all's path parameter, because the parameter drops both the query string and the
 * trailing slash PostHog's endpoints are addressed with (`/e/`, `/flags/`).
 */
const INGEST_ROUTE_PREFIX = '/api/ingest';

export default defineEventHandler(async (event) => {
    const { posthogHost } = useRuntimeConfig(event);
    const { pathname, search } = getRequestURL(event);
    const target = `${posthogHost}${pathname.slice(INGEST_ROUTE_PREFIX.length)}${search}`;
    delete event.node.req.headers.cookie;
    return proxyRequest(event, target);
});
