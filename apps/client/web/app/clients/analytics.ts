/**
 * The browser's PostHog client; the only module that imports posthog-js (spec: B-24, R-343).
 *
 * The browser sends PostHog's built-in pageview, identify, and reset calls and nothing else, so
 * autocapture and session recording are off: either could lift an email address off the page, and
 * B-24 says no event carries one. Identify takes the user's ID alone. Everything goes through the
 * `/api/ingest` Nitro proxy on the app's own origin, which ad blockers leave alone.
 *
 * Until `initializeAnalytics` runs, which it does only when a PostHog key is configured, identify
 * and reset do nothing, so a deployment without a key sends nothing at all.
 */
import posthog from 'posthog-js';

export const ANALYTICS_PROXY_PATH = '/api/ingest';

let isAnalyticsInitialized = false;

/** Start the SDK with the project key, sending through the proxy and recording pageviews. */
export function initializeAnalytics(projectKey: string): void {
    posthog.init(projectKey, {
        api_host: ANALYTICS_PROXY_PATH,
        capture_pageview: 'history_change',
        capture_pageleave: true,
        autocapture: false,
        disable_session_recording: true,
        person_profiles: 'identified_only',
    });
    isAnalyticsInitialized = true;
}

/** Tie later events to the signed-in user by ID, never by email. */
export function identifyAnalyticsUser(userId: string): void {
    if (isAnalyticsInitialized) {
        posthog.identify(userId);
    }
}

/** Forget the identified user, so the next visitor on this browser starts anonymous. */
export function resetAnalyticsUser(): void {
    if (isAnalyticsInitialized) {
        posthog.reset();
    }
}
