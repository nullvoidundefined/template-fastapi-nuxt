/**
 * The one typed client for the FastAPI backend (spec: Typed API client, B-4).
 *
 * openapi-fetch reads the paths, parameters, and bodies from `@repo/api-types`, which is
 * generated from the backend's OpenAPI document, so a call to a route the backend does not
 * define, or with the wrong shape, fails the type check. The caller supplies the base URL and
 * any headers to forward, such as the incoming cookie during server-side rendering, and every
 * request also carries `X-Requested-With: XMLHttpRequest` for the CSRF guard. Every response's
 * `X-Request-Id` becomes the Sentry `request_id` tag, so a browser error reported after a call
 * joins the backend's logs for that call (R-341).
 */
import type { paths } from '@repo/api-types';
import createClient, { type Client, type Middleware } from 'openapi-fetch';

import { tagErrorReportsWithRequestId } from '~/clients/errorReporting';

export type ApiClient = Client<paths>;

type ApiClientOptions = {
    baseUrl: string;
    headers?: Record<string, string>;
};

// The CSRF guard (B-6) rejects a state-changing request without this header, and the Nitro
// proxy only passes it through, so the client sets it on every request in both environments.
const baseHeaders = { 'X-Requested-With': 'XMLHttpRequest' };

const requestIdTagMiddleware: Middleware = {
    onResponse({ response }) {
        tagErrorReportsWithRequestId(response.headers.get('x-request-id'));
    },
};

/** Create a client that sends every request to `baseUrl` with the base and given headers. */
export function createApiClient({ baseUrl, headers }: ApiClientOptions): ApiClient {
    const apiClient = createClient<paths>({ baseUrl, headers: { ...baseHeaders, ...headers } });
    apiClient.use(requestIdTagMiddleware);
    return apiClient;
}
