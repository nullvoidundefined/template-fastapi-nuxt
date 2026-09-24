// Browser Sentry: enabled only when NUXT_PUBLIC_SENTRY_DSN is set, and never sending default PII.
import * as Sentry from '@sentry/nuxt';

import { buildSentryOptions } from './shared/services/buildSentryOptions';

Sentry.init(buildSentryOptions(useRuntimeConfig().public.sentryDsn));
