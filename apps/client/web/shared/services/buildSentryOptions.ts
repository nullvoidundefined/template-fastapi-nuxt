/**
 * The Sentry options both sides of the web app initialize with (spec: the Nuxt track's Sentry
 * section, B-30's client half).
 *
 * Shared because `sentry.client.config.ts` and `sentry.server.config.ts` must agree: with no DSN
 * the SDK is disabled outright, and neither side ever sends default PII, which for the browser SDK
 * would mean the visitor's IP address and cookies.
 */

type SentryOptions = {
    dsn: string | undefined;
    enabled: boolean;
    sendDefaultPii: false;
    tracesSampleRate: number;
};

/** Return the options for the given DSN, disabled when it is empty or missing. */
export function buildSentryOptions(sentryDsn: string | undefined): SentryOptions {
    return {
        dsn: sentryDsn || undefined,
        enabled: Boolean(sentryDsn),
        sendDefaultPii: false,
        tracesSampleRate: 0,
    };
}
