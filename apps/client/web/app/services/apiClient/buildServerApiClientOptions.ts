/**
 * Builds the server-side API client's options from the incoming page request (spec: Request path).
 *
 * During server-side rendering the client calls FastAPI directly at the absolute
 * `runtimeConfig.apiBaseUrl` and forwards exactly three things from the page request: the cookie,
 * so the call is authenticated as the user; the request ID (R-341), so logs correlate; and the
 * client's address as a single-value `X-Forwarded-For`, so rate limits count the user and not
 * Nitro. No other incoming header is forwarded.
 */
import { resolveClientAddress } from '#shared/services/resolveClientAddress';

type ServerApiClientSources = {
    apiBaseUrl: string;
    requestHeaders: Record<string, string | undefined>;
    socketAddress?: string;
};

type ServerApiClientOptions = {
    baseUrl: string;
    headers: Record<string, string>;
};

/** Return the base URL and the forwarded headers, refusing a base URL openapi-fetch cannot use. */
export function buildServerApiClientOptions({
    apiBaseUrl,
    requestHeaders,
    socketAddress,
}: ServerApiClientSources): ServerApiClientOptions {
    assertAbsoluteHttpUrl(apiBaseUrl);
    const clientAddress = resolveClientAddress(requestHeaders['x-forwarded-for'], socketAddress);
    const forwardedHeaders: Record<string, string | undefined> = {
        cookie: requestHeaders.cookie,
        'X-Request-Id': requestHeaders['x-request-id'],
        'X-Forwarded-For': clientAddress,
    };
    return { baseUrl: apiBaseUrl, headers: omitAbsentHeaders(forwardedHeaders) };
}

/** Throw unless the URL is absolute http(s) with a host, which a server-side Request needs. */
function assertAbsoluteHttpUrl(apiBaseUrl: string): void {
    const isAbsoluteHttpUrl =
        URL.canParse(apiBaseUrl) &&
        ['http:', 'https:'].includes(new URL(apiBaseUrl).protocol) &&
        new URL(apiBaseUrl).host !== '';
    if (!isAbsoluteHttpUrl) {
        throw new Error('NUXT_API_BASE_URL must be an absolute http(s) URL on the server');
    }
}

/** Drop headers whose source was absent from the page request. */
function omitAbsentHeaders(headers: Record<string, string | undefined>): Record<string, string> {
    return Object.fromEntries(
        Object.entries(headers).filter(
            (entry): entry is [string, string] => entry[1] !== undefined,
        ),
    );
}
