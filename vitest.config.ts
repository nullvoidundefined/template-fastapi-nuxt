// Root Vitest config: runs each package with its own config, so a test run started from the
// repository root (tdd.sh, CI, an editor) uses the Nuxt environment for the web app and plain
// Node for the tokens package.
import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        projects: ['apps/client/web', 'packages/tokens'],
    },
});
