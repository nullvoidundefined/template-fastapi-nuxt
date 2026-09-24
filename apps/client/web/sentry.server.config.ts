// Nitro Sentry: the same DSN rule as the browser, read from the environment because this file runs
// at server startup, before Nuxt's runtime config exists.
import * as Sentry from '@sentry/nuxt';

import { buildSentryOptions } from './shared/services/buildSentryOptions';

Sentry.init(buildSentryOptions(process.env.NUXT_PUBLIC_SENTRY_DSN));
