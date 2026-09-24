/**
 * Tells a route middleware that it is re-running for a navigation the server already gated
 * (IAN-335, spec: B-12, B-45).
 *
 * Nuxt runs route middleware on the server during a render and then again in the browser while
 * the page hydrates. For the session gates the second pass repeats a decision the server made for
 * the same navigation moments earlier, and repeating it costs a `GET /v1/auth/me` against the
 * global rate-limit bucket. A page the server rendered already passed the server's gate, and the
 * session the server fetched arrives in the query cache with the payload, so the browser pass can
 * stand down.
 */
import type { NuxtApp } from '#app';

/** Return true while the browser hydrates a page the server rendered. */
export function isHydratingServerRender(nuxtApp: NuxtApp): boolean {
    return (
        import.meta.client &&
        nuxtApp.isHydrating === true &&
        nuxtApp.payload.serverRendered === true
    );
}
