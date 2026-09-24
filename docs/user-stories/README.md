# User Stories

Every user-facing feature in template-fastapi-nuxt is documented as a user story (R-607). Each story carries a stable identifier, acceptance criteria as a checklist, and the path of the end-to-end spec that covers it.

## Convention

- One file per product area: `docs/user-stories/<area>.md`, matching one `## <Area>` section of `docs/feature-list/features.md`.
- Story identifiers are `US-<AREA>-NNN`, numbered in order within the area and never reused or renumbered.
- Each story has the "As / I want to / So that" form, an acceptance-criteria checklist, an `**E2E test:**` line naming the covering spec, and a `**Ticket:**` line.
- A branch that adds a page or an API route must also change `docs/feature-list/features.md`, a story file here, and an e2e spec; the push is refused otherwise (`scripts/require-feature-checklist.sh`, and the harness's `push-feature-docs-gate`).

## Files

| File                | Covers                                                                                                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `infrastructure.md` | Health endpoints, request IDs, the smoke suite, deploy configuration, and accessibility (US-INFRA-001 to US-INFRA-012, plus US-AUTH-001 to US-AUTH-003) |
| `landing.md`        | The landing page (US-LANDING-001)                                                                                                                       |
| `auth.md`           | The auth gate, the auth forms, and account recovery (US-AUTH-003 to US-AUTH-005)                                                                        |
| `admin.md`          | The admin user list (US-ADMIN-001)                                                                                                                      |
| `observability.md`  | Provider telemetry, PostHog and Sentry, and presigned uploads (US-OBS-001 to US-OBS-003)                                                                |
| `theme.md`          | The theme preference and toggle (US-THEME-001)                                                                                                          |
| `billing.md`        | Checkout, the billing portal, and the Stripe webhook (US-BILLING-001 to US-BILLING-003)                                                                 |
