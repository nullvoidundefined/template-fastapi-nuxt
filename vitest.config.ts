// Root Vitest config: runs each package with its own config, so a test run started from the
// repository root (tdd.sh, CI, an editor) uses the Nuxt environment for the web app and plain
// Node for the tokens package. `vitest run --coverage` enforces the web app's 60 percent floor
// (spec: CI coverage floors).
import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        projects: ['apps/client/web', 'packages/tokens'],
        coverage: {
            provider: 'v8',
            include: ['apps/client/web/app/**', 'apps/client/web/shared/**'],
            exclude: ['**/*.d.ts'],
            reporter: ['text-summary', 'text'],
            thresholds: { lines: 60, statements: 60, functions: 60, branches: 60 },
        },
    },
});
