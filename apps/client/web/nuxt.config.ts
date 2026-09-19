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
    modules: ['@nuxt/eslint', '@nuxt/test-utils/module'],
    css: ['~/assets/css/main.scss'],
    runtimeConfig: {
        apiBaseUrl: '',
        public: {},
    },
    typescript: { strict: true },
});
