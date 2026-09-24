/**
 * Turns a signed-out full page request away before it renders (spec: B-12).
 *
 * Presence only. It never calls the backend, never parses the cookie, and never decides whether
 * the session is valid: this runs in the Node process on every single request, and the real
 * verification happens once per navigation in the app, where `requireSession` reads the session
 * query. An expired-but-present cookie passes here and is caught there, which is the division of
 * labour Nitro middleware is suited to.
 *
 * It is closed by default. A page added next month without anyone touching this file is gated
 * rather than exposed, which is the failure mode worth choosing: a page wrongly gated is noticed
 * on the first visit, and a page wrongly exposed is noticed by whoever finds it.
 *
 * Every page response it lets through is marked `Cache-Control: no-store` (IAN-335). A page render
 * carries the session it was rendered with, and its HTML paints before any script can revalidate
 * that session, so this header is the control that keeps a revoked session's page off screen when
 * Back would replay it. The browser gate's recency check only decides what happens after
 * hydration and is no substitute for it.
 *
 * `/api/**` is skipped deliberately. A proxied call from the browser must receive the backend's
 * own 401 envelope; answering it with a 302 to an HTML sign-in page gives `fetch` a page to parse
 * as JSON, which fails somewhere far away from the cause.
 */
import { SESSION_COOKIE_NAME } from '#shared/constants/session';

const LOGIN_PATH = '/login';
// A found redirect: the visitor may come back to this page once they have signed in.
const FOUND_REDIRECT_STATUS = 302;
const PAGE_CACHE_CONTROL = 'no-store';
// The pages a signed-out visitor is meant to reach. `/login` is here for a reason of its own: a
// gate that redirected it would redirect it to itself, forever.
// The two recovery pages are reached from an email by someone who by definition cannot sign in.
const PUBLIC_PAGE_PATHS = new Set([
    '/',
    LOGIN_PATH,
    '/register',
    '/forgot-password',
    '/reset-password',
]);
// Prefixes served to anyone: the built bundle, and the files a browser asks for by convention.
const UNGATED_PATH_PREFIXES = ['/api/', '/_nuxt/', '/__nuxt', '/_ipx/'];
const UNGATED_EXACT_PATHS = new Set(['/favicon.ico', '/robots.txt', '/sitemap.xml']);

export default defineEventHandler((event) => {
    const requestPath = getRequestURL(event).pathname;
    if (isUngatedPath(requestPath)) {
        return undefined;
    }
    // Every page render can carry the visitor's session in its payload, so none may be stored:
    // a Back navigation replaying a stored render would paint a session revoked since.
    // Applies to every page; a future `routeRules` isr, swr, or prerender entry would conflict.
    setResponseHeader(event, 'cache-control', PAGE_CACHE_CONTROL);
    if (PUBLIC_PAGE_PATHS.has(requestPath)) {
        return undefined;
    }
    if (getCookie(event, SESSION_COOKIE_NAME)) {
        return undefined;
    }
    return sendRedirect(event, LOGIN_PATH, FOUND_REDIRECT_STATUS);
});

/** Return true for a path served without a session: the API, the bundle, and the well-known files. */
function isUngatedPath(requestPath: string): boolean {
    return (
        UNGATED_EXACT_PATHS.has(requestPath) ||
        UNGATED_PATH_PREFIXES.some((ungatedPrefix) => requestPath.startsWith(ungatedPrefix))
    );
}
