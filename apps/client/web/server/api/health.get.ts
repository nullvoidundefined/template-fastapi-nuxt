// Nitro route GET /api/health (US-INFRA-003): the web container's health check. It answers from
// the Nuxt server alone and never calls the backend, so a backend outage cannot fail this probe.
export default defineEventHandler(() => ({ status: 'ok' }));
