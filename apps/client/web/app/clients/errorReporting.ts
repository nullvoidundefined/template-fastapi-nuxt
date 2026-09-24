/**
 * The browser's Sentry calls outside initialization (spec: the Nuxt track's Sentry section, R-341).
 *
 * `sentry.client.config.ts` starts the SDK; this module only tags its scope, and does nothing
 * visible when the SDK was never enabled.
 */
import { setTag } from '@sentry/nuxt';

const REQUEST_ID_TAG = 'request_id';

/** Tag later error reports with the request ID the backend just answered with. */
export function tagErrorReportsWithRequestId(requestId: string | null): void {
    if (requestId) {
        setTag(REQUEST_ID_TAG, requestId);
    }
}
