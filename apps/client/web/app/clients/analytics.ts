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
import { stripQueryString } from '#shared/services/stripQueryString';

const ANALYTICS_PROXY_PATH = '/api/ingest';

let isAnalyticsInitialized = false;

/** Start the SDK with the project key, sending through the proxy and recording pageviews. */
function initializeAnalytics(projectKey: string): void {
    posthog.init(projectKey, {
        api_host: ANALYTICS_PROXY_PATH,
        autocapture: false,
        before_send: stripEventQueryStrings,
        capture_pageleave: true,
        capture_pageview: 'history_change',
        disable_session_recording: true,
        person_profiles: 'identified_only',
    });
    isAnalyticsInitialized = true;
}

/**
 * Drop the query string from every property of an event before it is sent, because the page URL,
 * the referrer and their siblings would otherwise carry a reset token to PostHog.
 */
function stripEventQueryStrings<T extends { properties?: Record<string, unknown> } | null>(
    event: T,
): T {
    if (!event?.properties) {
        return event;
    }
    const strippedProperties = Object.fromEntries(
        Object.entries(event.properties).map(([name, value]) => [name, stripQueryString(value)]),
    );
    return { ...event, properties: strippedProperties };
}

/** Tie later events to the signed-in user by ID, never by email. */
function identifyAnalyticsUser(userId: string): void {
    if (isAnalyticsInitialized) {
        posthog.identify(userId);
    }
}

/** Forget the identified user, so the next visitor on this browser starts anonymous. */
function resetAnalyticsUser(): void {
    if (isAnalyticsInitialized) {
        posthog.reset();
    }
}

/** The browser analytics client: start it, identify the signed-in user, and forget them. */
export const analyticsClient = {
    identifyUser: identifyAnalyticsUser,
    initialize: initializeAnalytics,
    resetUser: resetAnalyticsUser,
};
