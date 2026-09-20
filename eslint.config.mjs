// Root ESLint flat config: the files the web package's own config does not reach, namely the
// Playwright specs in `e2e/`, the `packages/` workspaces, and the configuration files at the
// repository root. `apps/` is ignored here because `apps/client/web` has its own Nuxt-generated
// config, whose rules are derived from that app's routes and layers and cannot be reproduced
// from the root, and `apps/server` is Python. Type-aware rules are deliberately not enabled:
// the files covered here span three tsconfigs, and the untyped recommended set catches the
// mistakes that matter in test and build code without a project service per workspace.
import js from '@eslint/js';
import globals from 'globals';
import typescriptEslint from 'typescript-eslint';

export default typescriptEslint.config(
    {
        ignores: [
            '**/node_modules/',
            '**/dist/',
            '**/.nuxt/',
            '**/.output/',
            'apps/',
            'playwright-report/',
            'test-results/',
            // Generated from apps/server/docs/openapi.yaml by openapi-typescript (spec B-4).
            'packages/api-types/src/schema.ts',
        ],
    },
    js.configs.recommended,
    ...typescriptEslint.configs.recommended,
    {
        files: ['**/*.{ts,mts,js,mjs}'],
        languageOptions: {
            globals: { ...globals.node },
        },
        rules: {
            // R-344: a catch that binds nothing cannot log the error it swallowed.
            'no-empty': ['error', { allowEmptyCatch: false }],
            'no-console': 'error',
            '@typescript-eslint/no-unused-vars': [
                'error',
                { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
            ],
        },
    },
    {
        // The Playwright specs run in the browser-facing test context, where `console` is the
        // only reporting channel a failing spec has outside the assertion itself.
        files: ['e2e/**/*.ts'],
        rules: { 'no-console': 'off' },
    },
);
