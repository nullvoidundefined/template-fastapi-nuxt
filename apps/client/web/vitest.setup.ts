/**
 * Vitest setup for the Nuxt test environment: makes the Fetch API globals come from one realm.
 *
 * With `domEnvironment: 'happy-dom'`, @nuxt/test-utils copies happy-dom's `fetch` and `Request`
 * onto the global scope but leaves Node's `Headers` in place, and happy-dom's Request silently
 * drops headers passed as a foreign Headers object. Libraries that build `new Headers()` and then
 * `new Request(url, { headers })`, as openapi-fetch does, would lose every header in tests though
 * they keep them in a browser or on the Nuxt server, where both classes share a realm. happy-dom's
 * Headers class is not exposed globally, so it is read from a Request instance's `headers`.
 */
const happyDomHeaders = new Request('http://localhost/').headers.constructor as typeof Headers;

if (globalThis.Headers !== happyDomHeaders) {
    globalThis.Headers = happyDomHeaders;
}
