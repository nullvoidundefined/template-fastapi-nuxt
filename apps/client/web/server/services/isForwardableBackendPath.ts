/**
 * Decides whether the backend proxy may forward a path (IAN-337 review, US-AUTH-003).
 *
 * The browser only ever calls `/api/v1/...`, so only `v1/` paths are forwarded. The check runs on
 * the path after percent-decoding, segment by segment, because the route receives the raw path
 * and `fetch` resolves `%2e%2e` into `..` when it builds the target: a raw `v1/%2e%2e/docs` starts
 * with `v1/` and still lands on `/docs`. Any dot segment, and any encoded slash that would create
 * one, is refused outright rather than resolved, since no API route contains one.
 */

const BACKEND_PATH_PREFIX = 'v1/';
const DOT_SEGMENTS = new Set(['.', '..']);

/** Return true only for a `v1/` path with no dot segment, encoded or not. */
export function isForwardableBackendPath(backendPath: string): boolean {
    let decodedPath: string;
    try {
        decodedPath = decodeURIComponent(backendPath);
    } catch {
        // A malformed escape cannot be a route this API serves.
        return false;
    }
    const segments = decodedPath.split('/');
    return (
        decodedPath.startsWith(BACKEND_PATH_PREFIX) &&
        !segments.some((segment) => DOT_SEGMENTS.has(segment))
    );
}
