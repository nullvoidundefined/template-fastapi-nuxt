/**
 * Tests that signing in and registering identify the user to PostHog, and signing out resets it
 * (spec: B-24, slice 07).
 *
 * The three auth mutations are driven end to end against a stubbed backend, and posthog-js is
 * replaced at its module boundary, so each assertion reads what the SDK itself was handed after a
 * real mutation succeeded. The email the backend answers with is in the fixture on purpose: the
 * check that no call to the SDK carries it is only meaningful when the data flowing past the
 * mutation contains one. A refused sign-in identifies no one.
 *
 * The analytics client is initialized once, as the plugin would in a deployment with a key; the
 * fetch stub is installed before the first mount for the reason `useSignOutMutation.test.ts`
 * explains, since openapi-fetch captures `globalThis.fetch` when the per-app client is built.
 */
import { describe, it, expect, afterEach, beforeAll, beforeEach, vi } from 'vitest';
import { defineComponent, h } from 'vue';
import { QueryClient, VueQueryPlugin, type VueQueryPluginOptions } from '@tanstack/vue-query';
import { mountSuspended } from '@nuxt/test-utils/runtime';

import { analyticsClient } from '~/clients/analytics';
import { buildQueryClientOptions } from '~/config/queryClient';
import { useRegisterMutation } from '~/composables/useRegisterMutation';
import { useSignInMutation } from '~/composables/useSignInMutation';
import { useSignOutMutation } from '~/composables/useSignOutMutation';

type PlannedResponse = { status: number; body?: unknown };

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

const signedInUser = { id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a', email: 'reader@example.test' };
const credentials = { email: signedInUser.email, password: ['long', 'enough', 'phrase'].join('-') };

let plannedResponse: PlannedResponse = { status: 200 };
let observedMutations:
    | {
          signIn: ReturnType<typeof useSignInMutation>;
          register: ReturnType<typeof useRegisterMutation>;
          signOut: ReturnType<typeof useSignOutMutation>;
      }
    | undefined;

const AuthMutationsProbe = defineComponent({
    name: 'AuthMutationsProbe',
    setup() {
        observedMutations = {
            signIn: useSignInMutation(),
            register: useRegisterMutation(),
            signOut: useSignOutMutation(),
        };
        return () => h('p', 'probe');
    },
});

/** Answer whatever the running test planned. */
async function answerPlannedResponse(): Promise<Response> {
    const { status, body } = plannedResponse;
    if (body === undefined) {
        return new Response(null, { status });
    }
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

/** Mount the probe and return the three mutations it created. */
async function mountAuthMutations(): Promise<NonNullable<typeof observedMutations>> {
    const vueQueryInstall: [typeof VueQueryPlugin, VueQueryPluginOptions] = [
        VueQueryPlugin,
        { queryClient: new QueryClient(buildQueryClientOptions()) },
    ];
    await mountSuspended(AuthMutationsProbe, { global: { plugins: [vueQueryInstall] } });
    if (!observedMutations) {
        throw new Error('The probe was never mounted, so no mutations were created');
    }
    return observedMutations;
}

/** Return the SDK calls other than initialization. */
function readIdentityCalls(): Array<{ method: string; args: unknown[] }> {
    return posthogCalls.filter((call) => call.method !== 'init');
}

beforeAll(() => {
    analyticsClient.initialize(['phc', 'identity', 'test'].join('_'));
});

beforeEach(() => {
    posthogCalls.length = 0;
    vi.stubGlobal('fetch', answerPlannedResponse);
});

afterEach(() => {
    observedMutations = undefined;
    vi.unstubAllGlobals();
});

describe('analytics identity across the auth mutations', () => {
    it('B-24: a successful sign-in identifies the user by ID only', async () => {
        plannedResponse = { status: 200, body: { data: signedInUser } };
        const { signIn } = await mountAuthMutations();

        await signIn.mutateAsync(credentials);

        expect(readIdentityCalls()).toEqual([{ method: 'identify', args: [signedInUser.id] }]);
        expect(JSON.stringify(posthogCalls)).not.toContain('@');
    });

    it('B-24: a successful registration identifies the user by ID only', async () => {
        plannedResponse = { status: 201, body: { data: signedInUser } };
        const { register } = await mountAuthMutations();

        await register.mutateAsync(credentials);

        expect(readIdentityCalls()).toEqual([{ method: 'identify', args: [signedInUser.id] }]);
        expect(JSON.stringify(posthogCalls)).not.toContain('@');
    });

    it('B-24: a successful sign-out resets the identified user', async () => {
        plannedResponse = { status: 204 };
        const { signOut } = await mountAuthMutations();

        await signOut.mutateAsync(undefined);

        expect(readIdentityCalls()).toEqual([{ method: 'reset', args: [] }]);
    });

    it('B-24: a refused sign-in identifies no one', async () => {
        plannedResponse = {
            status: 401,
            body: { code: 'AUTH_INVALID_CREDENTIALS', error: 'Invalid email or password' },
        };
        const { signIn } = await mountAuthMutations();

        await signIn.mutateAsync(credentials).catch(() => undefined);

        expect(readIdentityCalls()).toEqual([]);
    });
});
