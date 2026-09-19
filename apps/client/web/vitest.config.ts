// Vitest config: the Nuxt test environment, so components and Nitro routes run with Nuxt's runtime.
// rootDir is pinned to this directory so a run started from the repository root (the root
// Vitest projects config) still loads this Nuxt app rather than looking for one at the root.
import { fileURLToPath } from 'node:url';

import { defineVitestConfig } from '@nuxt/test-utils/config';

const webRootDirectory = fileURLToPath(new URL('.', import.meta.url));

export default defineVitestConfig({
    test: {
        environment: 'nuxt',
        environmentOptions: { nuxt: { domEnvironment: 'happy-dom', rootDir: webRootDirectory } },
        include: ['tests/**/*.test.ts'],
        setupFiles: ['./vitest.setup.ts'],
    },
});
