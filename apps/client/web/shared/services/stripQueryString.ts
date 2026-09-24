/**
 * Removes the query string and fragment from a URL or path (spec: B-24, B-30).
 *
 * Shared by browser Sentry and PostHog, which both record page URLs. A query string is where a
 * secret in a link lives, the reset token above all, so neither may ever send one. Values that are
 * not strings are returned unchanged, so a caller can pass any property through it.
 */

/** Return the value with everything from its first `?` or `#` removed. */
export function stripQueryString<T>(value: T): T {
    if (typeof value !== 'string') {
        return value;
    }
    const cutIndex = value.search(/[?#]/);
    return (cutIndex === -1 ? value : value.slice(0, cutIndex)) as T;
}
