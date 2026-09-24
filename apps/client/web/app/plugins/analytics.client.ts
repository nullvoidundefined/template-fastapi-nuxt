/**
 * Starts PostHog in the browser when `NUXT_PUBLIC_POSTHOG_KEY` is set (spec: B-24).
 *
 * Without a key nothing is initialized and every analytics call stays a no-op, which is what
 * development and the test suites run with.
 */
import { defineNuxtPlugin, useRuntimeConfig } from '#app';

import { initializeAnalytics } from '~/clients/analytics';

export default defineNuxtPlugin(() => {
    const { posthogKey } = useRuntimeConfig().public;
    if (posthogKey) {
        initializeAnalytics(posthogKey);
    }
});
