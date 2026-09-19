/**
 * The one typed client for the FastAPI backend (spec: Typed API client, B-4).
 *
 * openapi-fetch reads the paths, parameters, and bodies from `@repo/api-types`, which is
 * generated from the backend's OpenAPI document, so a call to a route the backend does not
 * define, or with the wrong shape, fails the type check. The caller supplies the base URL and
 * any headers to forward, such as the incoming cookie during server-side rendering.
 */
import type { paths } from '@repo/api-types';
import createClient, { type Client } from 'openapi-fetch';

export type ApiClient = Client<paths>;

type ApiClientOptions = {
    baseUrl: string;
    headers?: Record<string, string>;
};

/** Create a client that sends every request to `baseUrl` with the given headers. */
export function createApiClient({ baseUrl, headers }: ApiClientOptions): ApiClient {
    return createClient<paths>({ baseUrl, headers });
}
