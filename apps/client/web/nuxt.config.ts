// Nuxt configuration: the Nuxt 4 app/ root, SSR on, and runtime config read from NUXT_* variables.
export default defineNuxtConfig({
    compatibilityDate: '2026-09-01',
    devtools: { enabled: false },
    ssr: true,
    app: {
        head: {
            htmlAttrs: { lang: 'en' },
            title: 'template-fastapi-nuxt',
        },
    },
    modules: ['@nuxt/eslint', '@nuxt/test-utils/module', '@sentry/nuxt/module'],
    css: ['~/assets/css/main.scss'],
    runtimeConfig: {
        apiBaseUrl: '',
        // Where `/api/ingest` forwards PostHog traffic (NUXT_POSTHOG_HOST).
        posthogHost: 'https://us.i.posthog.com',
        public: {
            // Both empty by default, which leaves PostHog and Sentry off (NUXT_PUBLIC_*).
            posthogKey: '',
            sentryDsn: '',
        },
    },
    // Source maps upload from CI only, never from a developer machine (the Nuxt track's Sentry
    // section); without an auth token the module skips the upload.
    sentry: {
        telemetry: false,
    },
    typescript: { strict: true },
});
