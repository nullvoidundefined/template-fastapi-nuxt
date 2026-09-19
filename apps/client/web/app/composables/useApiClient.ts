/**
 * The typed API client for the current Nuxt app instance (spec: Request path).
 *
 * One client is memoized per Nuxt app instance, which on the server means one per request, and
 * never at module level: a server-side client holds one request's cookie, and a module outlives
 * the request. Call it only in setup and pass the client to the `app/api/` function. In the browser
 * it calls the Nitro proxy at `/api`; on the server it calls FastAPI directly with the page
 * request's cookie, request ID, and client address.
 */
import { useNuxtApp, useRequestEvent, useRequestHeaders, useRuntimeConfig } from '#imports';

import { type ApiClient, createApiClient } from '~/api/apiClient';
import { buildServerApiClientOptions } from '~/services/apiClient/buildServerApiClientOptions';

const browserApiBaseUrl = '/api';
// The only page-request headers the server-side client may forward (spec: Request path).
const forwardedRequestHeaderNames = ['cookie', 'x-request-id', 'x-forwarded-for'];
const apiClientsByNuxtApp = new WeakMap<object, ApiClient>();

/** Return this Nuxt app instance's client, creating it on first use. */
export function useApiClient(): ApiClient {
    const nuxtApp = useNuxtApp();
    const existingClient = apiClientsByNuxtApp.get(nuxtApp);
    if (existingClient) {
        return existingClient;
    }
    const apiClient = createApiClient(
        import.meta.server ? readServerApiClientOptions() : { baseUrl: browserApiBaseUrl },
    );
    apiClientsByNuxtApp.set(nuxtApp, apiClient);
    return apiClient;
}

/** Read the server-side options from the runtime config and the incoming page request. */
function readServerApiClientOptions(): ReturnType<typeof buildServerApiClientOptions> {
    return buildServerApiClientOptions({
        apiBaseUrl: useRuntimeConfig().apiBaseUrl,
        requestHeaders: useRequestHeaders(forwardedRequestHeaderNames),
        socketAddress: useRequestEvent()?.node.req.socket.remoteAddress,
    });
}
