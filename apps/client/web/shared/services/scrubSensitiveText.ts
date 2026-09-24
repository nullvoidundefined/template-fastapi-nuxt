/**
 * Redacts email addresses, bearer values, `name=value` secrets, and long opaque tokens from free
 * text (IAN-344), mirroring the server's `scrub_sensitive_text`.
 *
 * Used by the Sentry hooks on breadcrumb messages, exception values, and event messages, which can
 * quote an address or a reset token verbatim. A run of 32 or more URL-safe characters is treated
 * as a token (a session or reset token is 43), except a UUID, which is an identifier the event
 * needs to join its logs. Values that are not strings are returned unchanged.
 */

const REDACTED_TEXT = '[REDACTED]';
const EMAIL_PATTERN = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g;
const BEARER_PATTERN = /\b(bearer)\s+[^\s,;]+/gi;
const NAMED_SECRET_PATTERN = /\b(token|password|secret|api[_-]?key|session)=[^&\s,;]+/gi;
const OPAQUE_TOKEN_PATTERN =
    /(?<![A-Za-z0-9_-])(?![0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![A-Za-z0-9_-]))[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])/g;

/** Return the value with emails, bearer values, named secrets, and opaque tokens redacted. */
export function scrubSensitiveText<T>(value: T): T {
    if (typeof value !== 'string') {
        return value;
    }
    return value
        .replace(EMAIL_PATTERN, REDACTED_TEXT)
        .replace(BEARER_PATTERN, `$1 ${REDACTED_TEXT}`)
        .replace(NAMED_SECRET_PATTERN, `$1=${REDACTED_TEXT}`)
        .replace(OPAQUE_TOKEN_PATTERN, REDACTED_TEXT) as T;
}
