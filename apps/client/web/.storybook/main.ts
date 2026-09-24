/**
 * Storybook configuration (spec: the design spec's "Storybook" line, B-39).
 *
 * The `stories` glob and this file are what B-39's coverage test reads: it asks Storybook itself
 * what it indexes rather than listing files, so a story file this glob does not match counts as a
 * component without a story and fails that test. Keep the glob wide enough to cover every
 * component folder rather than naming directories one by one.
 */
import type { StorybookConfig } from '@storybook/vue3-vite';
import vue from '@vitejs/plugin-vue';
import { fileURLToPath } from 'node:url';

const config: StorybookConfig = {
    addons: ['@storybook/addon-a11y'],
    framework: { name: '@storybook/vue3-vite', options: {} },
    stories: ['../app/**/*.stories.ts'],
    // The vue3-vite framework expects the project to supply the Vue plugin; without it no `.vue`
    // file compiles and every story renders Storybook's error page instead of the component.
    // `#app` and `~` are Nuxt's; outside a Nuxt build they resolve to a shim and the app folder.
    viteFinal: (viteConfig) => ({
        ...viteConfig,
        plugins: [...(viteConfig.plugins ?? []), vue()],
        resolve: {
            ...viteConfig.resolve,
            alias: {
                ...viteConfig.resolve?.alias,
                '#app': fileURLToPath(new URL('./nuxtAppShim.ts', import.meta.url)),
                '~': fileURLToPath(new URL('../app', import.meta.url)),
            },
        },
    }),
};

export default config;
