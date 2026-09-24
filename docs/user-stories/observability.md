# Observability and Integrations User Stories

## US-OBS-001: Every provider call is logged, bounded, and correlated

**As** an operator of an application built from this template
**I want to** see every outbound provider call in the logs with its duration and outcome, under the request that made it
**So that** a slow or failing provider shows up by name instead of as an unexplained slow request

**Acceptance criteria:**

- [x] Every call through `with_client_telemetry` logs the provider, the operation, the duration, and the outcome, and re-raises a failure unchanged (spec B-23, R-346).
- [x] The caller's timeout bounds the whole call, and a call that outlives it is logged as a failure.
- [x] The request ID bound to the request is handed to the call as `X-Request-Id`, and a call made outside a request sends none.
- [x] The PostHog capture and the R2 presign both run through the wrapper.

**E2E test:** none; the wrapper is observable only in the server's logs, which `apps/server/tests/unit/clients/` asserts.
**Ticket:** IAN-337

---

## US-OBS-002: Analytics and error reports identify a person by ID only

**As** a person using an application built from this template
**I want to** be counted in analytics and named in error reports by an opaque ID, never by my email address
**So that** the product can be measured and debugged without spreading my address to third parties

**Acceptance criteria:**

- [x] Registering, signing in, signing out, and changing a password each send one server event to PostHog, named from the registry and keyed by the user's ID; no event carries an email address (spec B-24). The two password-reset events join these with the reset routes.
- [x] The browser sends pageviews through the `/api/ingest` proxy, calls `identify` with the user's ID after signing in and registering and `reset` after signing out, and has autocapture and session recording off (spec B-24).
- [x] The ingest proxy never forwards the session cookie to PostHog.
- [x] Sentry initializes only when `SENTRY_DSN` is set; an unhandled error's event carries the `request_id` tag and the user's ID, and cookies, the `Authorization` header, and frame locals are removed before it leaves the process (spec B-30).
- [x] In the web app, Sentry is enabled only when `NUXT_PUBLIC_SENTRY_DSN` is set, and both the browser and Nitro tag their scope with the request ID.
- [x] Without their keys, PostHog and Sentry log one warning and do nothing.

**E2E test:** none against the running stack, since neither provider is reachable from CI; `apps/server/tests/integration/routers/auth/test_auth_observability.py` drives the real application with each SDK replaced at its boundary.
**Ticket:** IAN-337

---

## US-OBS-003: Upload a file straight to storage under a key the server chose

**As** a signed-in person
**I want to** receive a short-lived URL I can upload a file to directly
**So that** a file reaches storage without passing through the API, and without my being able to choose, and so overwrite, where it lands

**Acceptance criteria:**

- [x] `POST /v1/uploads` presigns an R2 PUT for a key of the form `{user_id}/{uuid}.{extension}`, with the extension from the purpose's allowlist, the matching content type, and a 15-minute expiry (spec B-29).
- [x] A body that names its own key, or an extension outside the allowlist, answers 400 `INPUT_VALIDATION_ERROR` before any R2 call (spec B-29).
- [x] An anonymous request answers 401 and presigns nothing.
- [x] Without the four `R2_*` settings the route answers 503 `UPLOADS_STORAGE_UNCONFIGURED`.

**E2E test:** none yet; no page calls the route, and `apps/server/tests/integration/routers/uploads/` drives it through the real application.
**Ticket:** IAN-337
