/**
 * Tests that the web app's Sentry options redact tokens and emails inside free text (IAN-344).
 *
 * Query strings are already stripped from URLs. Free text is the remaining path: a breadcrumb's
 * `message` (a console line), an exception's `value`, and an event's `message` can each quote an
 * address or a reset token. Both hooks redact email addresses, bearer values, `name=value`
 * secrets, and long opaque tokens, and leave UUIDs readable so an event still joins its logs.
 *
 * Every secret-shaped value is built at run time, so no credential-shaped literal sits here (R-108).
 */
import { describe, it, expect } from 'vitest';

import { buildSentryOptions } from '../../../../shared/services/buildSentryOptions';

const sentryDsn = ['https://', 'publickey', '@', 'sentry.example.test', '/2'].join('');
const emailAddress = ['person', 'example.test'].join('@');

/** Return a value shaped like a reset or session token: 43 URL-safe characters. */
function buildRawToken(): string {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
    const randomBytes = crypto.getRandomValues(new Uint8Array(43));
    return Array.from(randomBytes, (randomByte) => alphabet[randomByte % alphabet.length]).join('');
}

describe('buildSentryOptions free-text scrubbing', () => {
    it('IAN-344: a breadcrumb message loses emails and tokens but keeps its words', () => {
        const { beforeBreadcrumb } = buildSentryOptions(sentryDsn);
        const rawToken = buildRawToken();

        const addressCrumb = beforeBreadcrumb({
            category: 'console',
            message: `reset requested for ${emailAddress}`,
        });
        const tokenCrumb = beforeBreadcrumb({
            category: 'console',
            message: `issued ${rawToken} and token=${rawToken}`,
        });

        expect(addressCrumb?.message).toBe('reset requested for [REDACTED]');
        expect(tokenCrumb?.message).not.toContain(rawToken);
        expect(tokenCrumb?.message?.startsWith('issued ')).toBe(true);
    });

    it('IAN-344: exception values and the event message lose emails, bearer values and secrets', () => {
        const { beforeSend } = buildSentryOptions(sentryDsn);
        const bearerValue = buildRawToken();
        const passwordValue = buildRawToken().slice(0, 12);

        const scrubbed = beforeSend({
            exception: {
                values: [
                    { type: 'Error', value: `no account for ${emailAddress}` },
                    { type: 'Error', value: `upstream refused Bearer ${bearerValue}` },
                    { type: 'Error', value: `bad login password=${passwordValue}` },
                ],
            },
            message: `failed for ${emailAddress}`,
        });

        const serialized = JSON.stringify(scrubbed);
        expect(serialized).not.toContain(emailAddress);
        expect(serialized).not.toContain(bearerValue);
        expect(serialized).not.toContain(passwordValue);
        expect(scrubbed?.exception?.values?.map((value) => value.type)).toEqual([
            'Error',
            'Error',
            'Error',
        ]);
    });

    it('IAN-344: a request ID in a message stays readable', () => {
        const { beforeBreadcrumb } = buildSentryOptions(sentryDsn);
        const requestId = crypto.randomUUID();
        const rawToken = buildRawToken();

        const breadcrumb = beforeBreadcrumb({
            category: 'console',
            message: `request ${requestId} used ${rawToken}`,
        });

        expect(breadcrumb?.message).toContain(requestId);
        expect(breadcrumb?.message).not.toContain(rawToken);
    });
});
