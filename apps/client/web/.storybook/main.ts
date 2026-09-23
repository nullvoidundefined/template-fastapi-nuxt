/**
 * Storybook configuration (spec: the design spec's "Storybook" line, B-39).
 *
 * The `stories` glob and this file are what B-39's coverage test reads: it asks Storybook itself
 * what it indexes rather than listing files, so a story file this glob does not match counts as a
 * component without a story and fails that test. Keep the glob wide enough to cover every
 * component folder rather than naming directories one by one.
 */
import type { StorybookConfig } from '@storybook/vue3-vite';

const config: StorybookConfig = {
    framework: { name: '@storybook/vue3-vite', options: {} },
    stories: ['../app/**/*.stories.ts'],
    addons: ['@storybook/addon-a11y'],
};

export default config;
