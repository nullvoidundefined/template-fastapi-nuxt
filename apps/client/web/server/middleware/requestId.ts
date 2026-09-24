/**
 * Gives every page request one ID, shared by the page response and the backend call (R-341).
 *
 * The ID is written back onto the incoming request headers, not only onto the response. The
 * server-side API client reads its forwarded headers from the request through
 * `useRequestHeaders(['cookie', 'x-request-id', 'x-forwarded-for'])`, so a middleware that set
 * only the response header would leave FastAPI minting a different ID, and the page and the API
 * calls it made would then correlate to nothing.
 *
 * An inbound ID is honored only when it is safe, by the same rule the backend applies: 1 to 64
 * characters of `[A-Za-z0-9._-]`. Echoing an arbitrary inbound value would let a client write
 * newlines or megabytes into every log line and response header.
 */
const REQUEST_ID_HEADER = 'x-request-id';
const SAFE_REQUEST_ID_PATTERN = /^[A-Za-z0-9._-]{1,64}$/;

export default defineEventHandler((event) => {
    const requestId = resolveRequestId(getRequestHeader(event, REQUEST_ID_HEADER));
    event.node.req.headers[REQUEST_ID_HEADER] = requestId;
    setResponseHeader(event, REQUEST_ID_HEADER, requestId);
});

/** Return the inbound ID when it is safe to repeat, else a fresh one. */
function resolveRequestId(inboundRequestId: string | undefined): string {
    if (inboundRequestId && SAFE_REQUEST_ID_PATTERN.test(inboundRequestId)) {
        return inboundRequestId;
    }
    return crypto.randomUUID();
}
