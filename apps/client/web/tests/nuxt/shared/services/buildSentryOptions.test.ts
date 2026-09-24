/**
 * Tests for the Sentry options both sides of the web app initialize with (spec: B-30's client
 * half, the Nuxt track's Sentry section, slice 07).
 *
 * `sentry.client.config.ts` and `sentry.server.config.ts` both build their options here from
 * `NUXT_PUBLIC_SENTRY_DSN`, so the rule is written once: no DSN means the SDK is disabled outright
 * rather than initialized against nothing, and neither side ever sends default PII, which for the
 * browser SDK would mean the visitor's IP address and cookies.
 */
import { describe, it, expect } from 'vitest';

import { buildSentryOptions } from '../../../../shared/services/buildSentryOptions';

// Built from parts so no DSN-shaped literal with a key sits in the source (R-108).
const sentryDsn = ['https://', 'publickey', '@', 'sentry.example.test', '/2'].join('');

describe('buildSentryOptions', () => {
    it('B-30: without a DSN, Sentry is disabled', () => {
        expect(buildSentryOptions('')).toMatchObject({ enabled: false, sendDefaultPii: false });
        expect(buildSentryOptions(undefined)).toMatchObject({ enabled: false });
        expect(buildSentryOptions('').dsn).toBeUndefined();
    });

    it('B-30: with a DSN, Sentry is enabled and still sends no default PII', () => {
        expect(buildSentryOptions(sentryDsn)).toMatchObject({
            dsn: sentryDsn,
            enabled: true,
            sendDefaultPii: false,
        });
    });
});
