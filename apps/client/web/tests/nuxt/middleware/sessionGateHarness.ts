/**
 * The shared rig for the client-side half of the auth gate (spec: slice 03 PR 3, B-12 and B-45).
 *
 * Three things about the Nuxt test environment shape everything here.
 *
 * First, one Nuxt app instance serves a whole test file. `useApiClient()` memoizes one API client
 * per app instance and openapi-fetch reads `globalThis.fetch` once, when that client is built, so
 * the first call in a file decides which fetch every later call goes through. A second
 * `vi.stubGlobal` in a later test would never be consulted. The stub installed here is therefore
 * one stable function that reads a mutable plan, and tests change the plan rather than the stub.
 *
 * Second, the same single app instance means the query client the app's own plugin installed
 * outlives each test, so `clearSessionCache()` runs between them. That is also what makes the
 * revalidation test meaningful: it can seed the cache the gate will read.
 *
 * Third, route middleware has no component instance, so it resolves its query client through
 * `inject` on the Nuxt app rather than on a component. `runRouteGate` reproduces exactly what
 * Nuxt's own router plugin does around a middleware call: it marks the app as processing
 * middleware, which is what makes `navigateTo` return its target instead of performing the
 * navigation, and it invokes the middleware through `nuxtApp.runWithContext`.
 */
import { vi } from 'vitest';
import type { RouteLocationRaw } from 'vue-router';
import { useNuxtApp, useRouter } from '#app';
import type { RouteMiddleware } from '#app';
import { useQueryClient } from '@tanstack/vue-query';
import type { QueryClient } from '@tanstack/vue-query';

import { sessionQueryKey } from '~/composables/useSessionQuery';

export type PlannedResponse = {
    status: number;
    body: unknown;
};

/** What a middleware call did: returned a value, or threw to abort the navigation. */
export type RouteGateOutcome =
    { settled: 'returned'; value: unknown } | { settled: 'threw'; error: unknown };

export const signedInUser = {
    id: '8f4a2f6e-0d5c-4a9b-9a4d-3d6f5e2c1b0a',
    email: 'reader@example.test',
};

const expiredSessionResponse: PlannedResponse = {
    status: 401,
    body: { code: 'AUTH_SESSION_EXPIRED', error: 'Your session has expired.' },
};

const backendOutageResponse: PlannedResponse = {
    status: 500,
    body: { code: 'INTERNAL_ERROR', error: 'Something went wrong.' },
};

let plannedResponse: PlannedResponse = expiredSessionResponse;
let sentRequests: Request[] = [];
let responseGate: Promise<void> = Promise.resolve();
let releaseResponseGate: () => void = () => {};

/** Record the request, wait for any hold the test placed, then answer the planned response. */
async function answerPlannedResponse(
    input: Parameters<typeof fetch>[0],
    init?: RequestInit,
): Promise<Response> {
    sentRequests.push(new Request(input, init));
    await responseGate;
    const { status, body } = plannedResponse;
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
    });
}

/** Install the one fetch stub the whole file shares. Call it before the first gate runs. */
export function installBackendStub(): void {
    vi.stubGlobal('fetch', answerPlannedResponse);
}

/** Set what `GET /v1/auth/me` answers next, releasing any hold and forgetting earlier requests. */
export function planBackendResponse(planned: PlannedResponse): void {
    plannedResponse = planned;
    sentRequests = [];
    releaseResponseGate();
    responseGate = Promise.resolve();
}

/** Plan a live session: the backend returns the signed-in user. */
export function planSignedInSession(): void {
    planBackendResponse({ status: 200, body: { data: signedInUser } });
}

/** Plan a rejected session: the backend answers 401, the signed-out and expired case. */
export function planExpiredSession(): void {
    planBackendResponse(expiredSessionResponse);
}

/** Plan a backend outage: a 500, which says nothing about whether the visitor is signed in. */
export function planBackendOutage(): void {
    planBackendResponse(backendOutageResponse);
}

/** Hold every answer until `releaseBackendResponse` runs, so the session stays unresolved. */
export function holdBackendResponse(): void {
    responseGate = new Promise<void>((resolve) => {
        releaseResponseGate = resolve;
    });
}

/** Let the held answer through. */
export function releaseBackendResponse(): void {
    releaseResponseGate();
}

/** Return the requests the stub has been sent since the plan was last set. */
export function readSentRequests(): Request[] {
    return sentRequests;
}

/** Return the query client the application's own plugin installed for this Nuxt app instance. */
export async function readAppQueryClient(): Promise<QueryClient> {
    return useNuxtApp().runWithContext(() => useQueryClient());
}

/** Seed the cache with a session the gate will find already there. */
export async function seedCachedSession(user: typeof signedInUser): Promise<void> {
    const queryClient = await readAppQueryClient();
    queryClient.setQueryData(sessionQueryKey, user);
}

/** Empty the cache and cancel anything in flight, so one test cannot answer the next one. */
export async function clearSessionCache(): Promise<void> {
    const queryClient = await readAppQueryClient();
    await queryClient.cancelQueries();
    queryClient.clear();
}

/**
 * Run a route middleware the way Nuxt's router plugin runs it, and report how it settled.
 *
 * The route locations are resolved by the application's own router, so `to` carries the real
 * record and its meta for the path under test. The casts are the harness admitting that
 * `router.resolve` returns a resolved location while a middleware is typed against a normalized
 * one; the two differ in fields no auth middleware reads.
 */
export async function runRouteGate(
    middleware: RouteMiddleware,
    toPath: string,
    fromPath = '/',
): Promise<RouteGateOutcome> {
    const nuxtApp = useNuxtApp();
    const router = useRouter();
    const to = router.resolve(toPath) as unknown as Parameters<RouteMiddleware>[0];
    const from = router.resolve(fromPath) as unknown as Parameters<RouteMiddleware>[1];
    nuxtApp._processingMiddleware = true;
    try {
        const value = await nuxtApp.runWithContext(() => middleware(to, from));
        return { settled: 'returned', value };
    } catch (error) {
        return { settled: 'threw', error };
    } finally {
        delete nuxtApp._processingMiddleware;
    }
}

/**
 * Return the path a middleware's returned redirect would navigate to, or undefined when it let the
 * navigation through. The value goes through the router rather than being compared as a string, so
 * `navigateTo('/login')` and `navigateTo({ name: 'login' })` are judged by where they send the
 * visitor rather than by how the call was spelled.
 */
export function readRedirectPath(outcome: RouteGateOutcome): string | undefined {
    if (outcome.settled !== 'returned') {
        return undefined;
    }
    const { value } = outcome;
    if (typeof value !== 'string' && (typeof value !== 'object' || value === null)) {
        return undefined;
    }
    return useRouter().resolve(value as RouteLocationRaw).path;
}
