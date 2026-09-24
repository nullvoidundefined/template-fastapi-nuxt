/**
 * The Sentry options both sides of the web app initialize with (spec: the Nuxt track's Sentry
 * section, B-30's client half).
 *
 * Shared because `sentry.client.config.ts` and `sentry.server.config.ts` must agree: with no DSN
 * the SDK is disabled outright, and neither side ever sends default PII, which for the browser SDK
 * would mean the visitor's IP address and cookies. Every URL an event or breadcrumb carries loses
 * its query string, because the reset page's address holds a live reset token. Free text (a
 * breadcrumb's message, an exception's value, the event's message) loses emails and tokens.
 */
import { scrubSensitiveText } from './scrubSensitiveText';
import { stripQueryString } from './stripQueryString';

type SentryEventLike = {
    exception?: { values?: Array<{ type?: string; value?: string }> };
    message?: string;
    request?: { query_string?: unknown; url?: string };
};

type SentryBreadcrumbLike = {
    category?: string;
    data?: Record<string, unknown>;
    message?: string;
};

type SentryOptions = {
    beforeBreadcrumb: <T extends SentryBreadcrumbLike>(breadcrumb: T) => T | null;
    beforeSend: <T extends SentryEventLike>(event: T) => T | null;
    dsn: string | undefined;
    enabled: boolean;
    sendDefaultPii: false;
    tracesSampleRate: number;
};

/** Return the options for the given DSN, disabled when it is empty or missing. */
export function buildSentryOptions(sentryDsn: string | undefined): SentryOptions {
    return {
        beforeBreadcrumb: scrubBreadcrumb,
        beforeSend: scrubEvent,
        dsn: sentryDsn || undefined,
        enabled: Boolean(sentryDsn),
        sendDefaultPii: false,
        tracesSampleRate: 0,
    };
}

/** Strip the event's query strings, then scrub its message and exception values. */
function scrubEvent<T extends SentryEventLike>(event: T): T {
    return scrubEventText(stripEventQuery(event));
}

/** Strip the breadcrumb's query strings, then scrub its message. */
function scrubBreadcrumb<T extends SentryBreadcrumbLike>(breadcrumb: T): T {
    const strippedBreadcrumb = stripBreadcrumbQueries(breadcrumb);
    if (strippedBreadcrumb.message === undefined) {
        return strippedBreadcrumb;
    }
    return { ...strippedBreadcrumb, message: scrubSensitiveText(strippedBreadcrumb.message) };
}

/** Redact emails and tokens from the event's message and every exception value. */
function scrubEventText<T extends SentryEventLike>(event: T): T {
    const { exception, message } = event;
    const scrubbedEvent =
        message === undefined ? event : { ...event, message: scrubSensitiveText(message) };
    if (!exception?.values) {
        return scrubbedEvent;
    }
    const scrubbedValues = exception.values.map((exceptionValue) => ({
        ...exceptionValue,
        value: scrubSensitiveText(exceptionValue.value),
    }));
    return { ...scrubbedEvent, exception: { ...exception, values: scrubbedValues } };
}

/** Drop the query string from the event's request URL and the parsed copy Sentry keeps. */
function stripEventQuery<T extends SentryEventLike>(event: T): T {
    const { request } = event;
    if (!request) {
        return event;
    }
    const { query_string: _queryString, ...requestWithoutQuery } = request;
    return { ...event, request: { ...requestWithoutQuery, url: stripQueryString(request.url) } };
}

/** Drop the query string from every value a navigation or request breadcrumb carries. */
function stripBreadcrumbQueries<T extends SentryBreadcrumbLike>(breadcrumb: T): T {
    const { data } = breadcrumb;
    if (!data) {
        return breadcrumb;
    }
    const strippedData = Object.fromEntries(
        Object.entries(data).map(([name, value]) => [name, stripQueryString(value)]),
    );
    return { ...breadcrumb, data: strippedData };
}
