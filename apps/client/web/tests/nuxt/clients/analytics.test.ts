/**
 * Tests for the browser PostHog client `app/clients/analytics.ts` (spec: B-24, slice 07).
 *
 * The client is the only module that imports posthog-js, so the SDK is replaced here at its own
 * module boundary and every assertion reads what the SDK was handed. Four things are pinned: the
 * SDK sends through the `/api/ingest` proxy rather than to PostHog's domain, which ad blockers
 * drop; it records pageviews on every client-side navigation and nothing it was not asked for
 * (no autocapture, no session recording, either of which could lift an email address off the
 * page); identify carries the user's ID and nothing else; and before initialization, which is the
 * state of every deployment without a PostHog key, identify and reset do nothing at all.
 *
 * The module holds whether it was initialized, so each test imports a fresh copy.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const posthogCalls = vi.hoisted(() => [] as Array<{ method: string; args: unknown[] }>);

vi.mock('posthog-js', () => {
    const recordCall =
        (method: string) =>
        (...args: unknown[]) => {
            posthogCalls.push({ method, args });
        };
    return {
        default: {
            init: recordCall('init'),
            identify: recordCall('identify'),
            reset: recordCall('reset'),
            capture: recordCall('capture'),
        },
    };
});

const userId = '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a';
const projectKey = ['phc', 'browser', 'test'].join('_');

/** Import a fresh copy of the client, so no test inherits another's initialization. */
async function importAnalyticsClient(): Promise<
    (typeof import('~/clients/analytics'))['analyticsClient']
> {
    vi.resetModules();
    return (await import('~/clients/analytics')).analyticsClient;
}

beforeEach(() => {
    posthogCalls.length = 0;
});

describe('the browser analytics client', () => {
    it('B-24: before initialization, identify and reset send nothing', async () => {
        const analytics = await importAnalyticsClient();

        analytics.identifyUser(userId);
        analytics.resetUser();

        expect(posthogCalls).toEqual([]);
    });

    it('B-24: initializes through the ingest proxy with pageviews on and autocapture off', async () => {
        const analytics = await importAnalyticsClient();

        analytics.initialize(projectKey);

        expect(posthogCalls).toHaveLength(1);
        const [initCall] = posthogCalls;
        expect(initCall!.method).toBe('init');
        expect(initCall!.args[0]).toBe(projectKey);
        expect(initCall!.args[1]).toMatchObject({
            api_host: '/api/ingest',
            capture_pageview: 'history_change',
            autocapture: false,
            disable_session_recording: true,
        });
    });

    it('B-24: identify sends the user ID and nothing else', async () => {
        const analytics = await importAnalyticsClient();
        analytics.initialize(projectKey);
        posthogCalls.length = 0;

        analytics.identifyUser(userId);

        expect(posthogCalls).toEqual([{ method: 'identify', args: [userId] }]);
    });

    it('B-24: reset forgets the identified user', async () => {
        const analytics = await importAnalyticsClient();
        analytics.initialize(projectKey);
        posthogCalls.length = 0;

        analytics.resetUser();

        expect(posthogCalls).toEqual([{ method: 'reset', args: [] }]);
    });
});
