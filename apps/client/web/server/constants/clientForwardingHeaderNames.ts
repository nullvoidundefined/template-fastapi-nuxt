/**
 * The headers a client can set to claim an address, scheme, host, port, or path prefix it did not
 * use (IAN-335, US-AUTH-003, B-24). Both Nitro proxies withhold every one of them: the backend
 * proxy because uvicorn trusts them from Nitro's address, and the PostHog proxy because PostHog
 * has no use for them. One list keeps the two from drifting apart.
 */
export const CLIENT_FORWARDING_HEADER_NAMES = [
    'forwarded',
    'x-forwarded-for',
    'x-forwarded-host',
    'x-forwarded-port',
    'x-forwarded-prefix',
    'x-forwarded-proto',
    'x-real-ip',
];
