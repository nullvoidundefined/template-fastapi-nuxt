# Observability

This is the catalog of everything the application can dispatch: request IDs, analytics events,
structured log events, error codes, error reporting, outbound-call telemetry, and health
endpoints. It is drawn from the code on the branch that carries every slice through slice 08,
billing (Stripe checkout, the portal, and the webhook ledger) and closing work (the hourly
`delete_expired_rows` cleanup job, the smoke suite, and the Railway healthcheck paths) included.

## a. Request IDs and correlation

Every browser request gets one ID that is bound to every log line, every error report, and every
outbound call for that request (R-341).

- **Nitro (the web app's server).** `apps/client/web/server/middleware/requestId.ts` runs first
  on every request. It accepts an inbound `X-Request-Id` only when it matches
  `^[A-Za-z0-9._-]{1,64}$`, mints a fresh UUID otherwise, writes the value back onto the
  _incoming_ request headers (not only the response), sets it as the response header, and tags
  the request's Sentry isolation scope with it. Writing it onto the incoming headers matters
  because the server-side API client later reads it back out with
  `useRequestHeaders(['cookie', 'x-request-id', 'x-forwarded-for'])` to forward to FastAPI.
- **The `/api/[...path]` proxy.** `apps/client/web/server/api/[...path].ts` forwards whatever
  request-ID header is present on the proxied call (it does not strip or replace it, unlike
  `X-Forwarded-For`, which it does replace).
- **FastAPI.** `asgi-correlation-id`'s `CorrelationIdMiddleware`, registered outermost in
  `apps/server/app/main.py`, validates an inbound `X-Request-Id` with
  `is_valid_request_id` (the same character-and-length rule as the Nitro middleware), mints one
  when none is present or the inbound value is invalid, and echoes it on every response including
  a rejection from a guard. `RequestContextMiddleware`
  (`apps/server/app/middleware/request_context.py`) binds `correlation_id.get()` into structlog's
  context for the request's duration with `structlog.contextvars.bound_contextvars`, and calls
  `tag_sentry_request` to tag the request's Sentry scope.
- **Propagation to jobs.** `POST /v1/auth/forgot-password` reads the bound request ID with
  `structlog.contextvars.get_contextvars().get("request_id")` and passes it as an argument to the
  `send_password_reset_email` job. The job rebinds it into its own structlog context in
  `issue_and_send_reset_email`, alongside the arq `job_id`, so every log line the job writes and
  the Resend call it makes carry both IDs.
- **Propagation to outbound calls.** `apps/server/app/clients/telemetry.py`'s
  `build_forwarded_headers` reads the bound request ID (if any) and returns it as an
  `X-Request-Id` header for the provider call to send, so Resend's, PostHog's, and R2's own logs
  can in principle be joined to this application's.
- **A 500's request ID.** The catch-all exception handler
  (`apps/server/app/main.py::handle_unexpected_error`) reads `correlation_id.get()` directly
  rather than through structlog context, because Starlette moves an `Exception`-keyed handler to
  `ServerErrorMiddleware`, outside the correlation middleware; the handler sets the header by hand
  for this one response.

## b. Analytics events

### Server events (PostHog, via `AnalyticsClient`)

Every server-side event is a member of `apps/server/app/analytics/events.py`'s `AnalyticsEvent`
`StrEnum` (R-343); no call site passes a bare string. Each is keyed on the user's ID (a UUID) as
PostHog's `distinct_id`, and carries one property, `request_id`, when a request ID is bound
(`apps/server/app/clients/analytics.py::build_event_properties`). No event carries an email
address or any other PII.

| Event                           | Trigger (file, route)                                                                                                                                                             | Identity key                                         | Properties                                     |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- | ---------------------------------------------- |
| `USER_REGISTERED`               | `apps/server/app/routers/auth.py::register`, `POST /v1/auth/register`                                                                                                             | the new user's ID                                    | `request_id` if bound                          |
| `USER_SIGNED_IN`                | `apps/server/app/routers/auth.py::login`, `POST /v1/auth/login`                                                                                                                   | the signed-in user's ID                              | `request_id` if bound                          |
| `USER_SIGNED_OUT`               | `apps/server/app/routers/auth.py::logout`, `POST /v1/auth/logout` (only when a session existed)                                                                                   | the signed-out user's ID                             | `request_id` if bound                          |
| `USER_PASSWORD_CHANGED`         | `apps/server/app/routers/auth.py::change_my_password`, `PATCH /v1/auth/me`                                                                                                        | the user's ID                                        | `request_id` if bound                          |
| `USER_PASSWORD_RESET_REQUESTED` | `apps/server/app/workers/jobs/send_password_reset_email.py::issue_and_send_reset_email`, enqueued from `POST /v1/auth/forgot-password` (only when the address matches an account) | the user's ID (found by the job, never by the route) | `request_id` if the enqueueing request had one |
| `USER_PASSWORD_RESET_COMPLETED` | `apps/server/app/routers/auth.py::reset_password_with_token`, `POST /v1/auth/reset-password`                                                                                      | the user's ID (resolved from the consumed token)     | `request_id` if bound                          |

A capture failure is logged as `analytics_capture_failed` and swallowed (see Structured log
events); it never fails the request or job that triggered it. Without `POSTHOG_API_KEY` the
client is a no-op and logs `analytics_disabled` once at startup. A shutdown that outlasts the SDK's
flush timeout is logged as `analytics_shutdown_timed_out` rather than blocking process exit.

Billing has no entry in the `AnalyticsEvent` registry. Checkout, the portal, and every webhook
outcome are recorded only as structured log events (see below), not as PostHog captures.

### Browser events (PostHog, via `posthog-js`)

`apps/client/web/app/clients/analytics.ts` is the only module that imports `posthog-js`.
Autocapture and session recording are both off. The only calls the browser makes are:

- **Pageview and pageleave** - PostHog's own `capture_pageview: 'history_change'` and
  `capture_pageleave: true`, configured in `initializeAnalytics`. No call site in this codebase
  triggers these directly; the SDK fires them on navigation.
- **Identify** - `analyticsClient.identifyUser(userId)`, called with the user's ID (never an
  email) from `useRegisterMutation.ts` and `useSignInMutation.ts` after a successful register or
  sign-in.
- **Reset** - `analyticsClient.resetUser()`, called from `useSignOutMutation.ts` after a
  successful sign-out, so the next visitor on that browser starts anonymous.

Before any event, pageview, or breadcrumb-like payload leaves the browser, `before_send` strips
the query string from every property value (`stripEventQueryStrings`), because a reset-password
page's URL carries a live token in its query string.

### The ingest proxy

`apps/client/web/server/api/ingest/[...path].ts` proxies `/api/ingest/<rest>` to
`runtimeConfig.posthogHost`, so an ad blocker that drops third-party PostHog domains does not
drop first-party traffic to the app's own origin. It allows only PostHog's known ingest paths
(events, batch, flags, decide, and static assets) by regex, strips the visitor's cookie and every
forwarding header before proxying (`WITHHELD_HEADER_NAMES`), and refuses to forward anywhere that
is not the resolved PostHog origin.

## c. Structured log events

Every log call in `apps/server/app` goes through structlog (`logger = structlog.get_logger(...)`
or an inline `structlog.get_logger()`), never the standard library's `logging` or `print` (R-342).
This table lists every event name a `logger.<level>(...)` call in `apps/server/app` uses, its
level, where it fires, and its fields.

| Event                                       | Level   | Fires in                                                                                                                | Fields                                                                  |
| ------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `request_database_unavailable`              | warning | `main.py::handle_database_unavailable`                                                                                  | `error_type`                                                            |
| `request_unhandled_exception`               | error   | `main.py::handle_unexpected_error` (the 500 handler)                                                                    | `exc_info`, `request_id`                                                |
| `readiness_db_failed`                       | warning | `routers/health.py::read_readiness`                                                                                     | `exc_info`                                                              |
| `user_registered`                           | info    | `routers/auth.py::register`                                                                                             | `user_id`                                                               |
| `user_signed_in`                            | info    | `routers/auth.py::login`                                                                                                | `user_id`                                                               |
| `user_signed_out`                           | info    | `routers/auth.py::logout`                                                                                               | `user_id`                                                               |
| `user_password_changed`                     | info    | `routers/auth.py::change_my_password`                                                                                   | `user_id`                                                               |
| `user_password_reset`                       | info    | `routers/auth.py::reset_password_with_token`                                                                            | `user_id`                                                               |
| `billing_checkout_created`                  | info    | `routers/billing.py::create_checkout`                                                                                   | `user_id`                                                               |
| `billing_portal_created`                    | info    | `routers/billing.py::create_portal`                                                                                     | `user_id`                                                               |
| `client_call_failed`                        | warning | `clients/telemetry.py::with_client_telemetry` (any provider call that raised)                                           | `provider`, `operation`, `duration_ms`, `outcome`, `exc_info`           |
| `client_call_failed` (upload)               | warning | `clients/analytics.py::log_upload_failure` (PostHog's `on_error`, on the SDK's consumer thread, after its retries)      | `provider`, `operation` (`upload`), `outcome`, `batch_size`, `exc_info` |
| `client_call_succeeded`                     | info    | `clients/telemetry.py::with_client_telemetry` (any provider call that returned)                                         | `provider`, `operation`, `duration_ms`, `outcome`                       |
| `stripe_webhook_signature_rejected`         | warning | `clients/stripe.py::construct_webhook_event` (the SDK's own signature check)                                            | `exc_info`                                                              |
| `analytics_capture_failed`                  | warning | `clients/analytics.py::track_event`                                                                                     | `analytics_event`, `exc_info`                                           |
| `analytics_disabled`                        | warning | `clients/analytics.py::create_analytics_client` (startup, no key)                                                       | `reason`                                                                |
| `analytics_shutdown_timed_out`              | warning | `clients/analytics.py::AnalyticsClient.close` (the flush outlasted its timeout)                                         | `timeout_seconds`                                                       |
| `password_reset_email_not_sent`             | warning | `clients/disabled_email.py` (the no-op stand-in, when called without a Resend key)                                      | `reason`                                                                |
| `idempotency_database_unavailable`          | warning | `middleware/idempotency.py`                                                                                             | `error_type`                                                            |
| `idempotency_replayed`                      | info    | `middleware/idempotency.py`                                                                                             | `path`                                                                  |
| `idempotency_key_reused`                    | warning | `middleware/idempotency.py`                                                                                             | `path`                                                                  |
| `idempotency_claim_taken_over`              | info    | `middleware/idempotency.py`                                                                                             | `path`                                                                  |
| `idempotency_response_not_json`             | warning | `middleware/idempotency.py`                                                                                             | `path`                                                                  |
| `idempotency_completion_failed`             | error   | `middleware/idempotency.py`                                                                                             | `exc_info`, `path`                                                      |
| `idempotency_claim_superseded`              | warning | `middleware/idempotency.py`                                                                                             | `path`                                                                  |
| `idempotency_release_failed`                | error   | `middleware/idempotency.py`                                                                                             | `exc_info`, `path`                                                      |
| `error_reporting_disabled`                  | warning | `clients/sentry.py::initialize_sentry` (startup, no DSN)                                                                | `reason`                                                                |
| `storage_disabled`                          | warning | `clients/r2.py::create_r2_client` (startup, incomplete R2 settings)                                                     | `reason`                                                                |
| `billing_webhook_misconfigured`             | warning | `services/billing/verify_webhook_event.py::verify_webhook_event` (no signature header or no signing secret)             | `has_signature`, `has_signing_secret`                                   |
| `billing_webhook_signature_invalid`         | warning | `services/billing/verify_webhook_event.py::verify_webhook_event`                                                        | `exc_info`                                                              |
| `billing_webhook_event_ignored`             | info    | `services/billing/process_webhook_event.py::process_webhook_event` (event type outside the allowlist)                   | `event_type`                                                            |
| `billing_webhook_event_skipped`             | info    | `services/billing/process_webhook_event.py::process_webhook_event` (already processed)                                  | `stripe_event_id`                                                       |
| `billing_webhook_event_in_progress`         | info    | `services/billing/process_webhook_event.py::process_webhook_event` (a live claim held by another delivery)              | `stripe_event_id`                                                       |
| `billing_webhook_event_failed`              | error   | `services/billing/process_webhook_event.py::process_webhook_event` (the handler raised)                                 | `exc_info`, `stripe_event_id`, `event_type`                             |
| `billing_webhook_event_processed`           | info    | `services/billing/process_webhook_event.py::process_webhook_event`                                                      | `stripe_event_id`, `event_type`                                         |
| `billing_webhook_mark_failed_failed`        | error   | `services/billing/process_webhook_event.py::mark_event_failed_safely` (marking the event failed also failed)            | `exc_info`, `stripe_event_id`                                           |
| `billing_checkout_unlinkable`               | warning | `services/billing/apply_webhook_event.py::apply_checkout_completed` (no user, customer, or subscription in the session) | `checkout_session_id`                                                   |
| `billing_checkout_link_ignored`             | info    | `services/billing/apply_webhook_event.py::apply_checkout_completed`                                                     | `stripe_subscription_id`                                                |
| `billing_subscription_unmatched`            | info    | `services/billing/apply_webhook_event.py::apply_subscription_change` (no existing row and no metadata user ID)          | `stripe_subscription_id`                                                |
| `billing_subscription_event_ignored`        | info    | `services/billing/apply_webhook_event.py::apply_subscription_change`                                                    | `stripe_subscription_id`, `user_id`                                     |
| `billing_invoice_without_subscription`      | info    | `services/billing/apply_webhook_event.py::apply_payment_failed`                                                         | `stripe_invoice_id`                                                     |
| `billing_payment_failure_ignored`           | info    | `services/billing/apply_webhook_event.py::apply_payment_failed`                                                         | `stripe_subscription_id`                                                |
| `billing_link_user_missing`                 | warning | `services/billing/apply_webhook_event.py::is_linkable_to_user` (the user row does not exist)                            | `user_id`                                                               |
| `billing_link_customer_owned_by_other_user` | warning | `services/billing/apply_webhook_event.py::is_linkable_to_user`                                                          | `stripe_customer_id`, `user_id`                                         |
| `billing_metadata_user_id_invalid`          | warning | `services/billing/apply_webhook_event.py::read_metadata_user_id` (the metadata's user ID is not a UUID)                 | `exc_info`                                                              |
| `request_timed_out`                         | warning | `middleware/request_timeout.py`                                                                                         | `path`, `timeout_seconds`                                               |
| `rate_limiter_in_memory`                    | warning | `middleware/rate_limit.py` (no `REDIS_URL` outside production)                                                          | none                                                                    |
| `rate_limiter_unavailable`                  | error   | `middleware/rate_limit.py` (Redis unreachable)                                                                          | `error_type`, `path`                                                    |
| `csrf_header_missing`                       | warning | `middleware/csrf_guard.py`                                                                                              | `method`, `path`                                                        |
| `session_expired`                           | info    | `dependencies/current_user.py`                                                                                          | `session_id`                                                            |
| `admin_access_refused`                      | warning | `dependencies/admin_user.py`                                                                                            | `user_id`                                                               |
| `request_database_connect_failed`           | warning | `db/session.py::get_connection`                                                                                         | `error_type`                                                            |
| `worker_readiness_db_failed`                | warning | `workers/health.py::check_database`                                                                                     | `exc_info`                                                              |
| `worker_readiness_redis_failed`             | warning | `workers/health.py::check_redis`                                                                                        | `exc_info`                                                              |
| `worker_heartbeat`                          | info    | `workers/jobs/log_worker_heartbeat.py` (the five-minute cron job)                                                       | none                                                                    |
| `password_reset_email_failed`               | error   | `workers/jobs/send_password_reset_email.py` (last retry exhausted)                                                      | `job_try`, `err`                                                        |
| `password_reset_email_retrying`             | warning | `workers/jobs/send_password_reset_email.py`                                                                             | `job_try`, `err`                                                        |
| `password_reset_email_skipped`              | info    | `workers/jobs/send_password_reset_email.py` (address matches no account)                                                | none                                                                    |
| `password_reset_email_sent`                 | info    | `workers/jobs/send_password_reset_email.py`                                                                             | `user_id`                                                               |
| `expired_rows_deleted`                      | info    | `workers/jobs/delete_expired_rows.py::delete_expired_rows` (the hourly cleanup cron job, once per table)                | `table`, `deleted_count`                                                |
| `worker_started`                            | info    | `workers/settings.py::start_worker_resources`                                                                           | `worker_port`                                                           |
| `email_disabled`                            | warning | `workers/settings.py::create_email_client` (startup, no Resend key)                                                     | `reason`                                                                |
| `worker_stopped`                            | info    | `workers/settings.py::stop_worker_resources`                                                                            | none                                                                    |

**A naming gap found while cataloging.** `routers/auth.py::reset_password_with_token` logs
`user_password_reset`, but the analytics event it fires immediately after is
`USER_PASSWORD_RESET_COMPLETED` (value `user_password_reset_completed`). Every other route logs
and tracks under the same name (`user_registered`/`USER_REGISTERED`,
`user_signed_in`/`USER_SIGNED_IN`, and so on); this one pair has drifted. Neither is wrong on its
own, but a log search for `user_password_reset_completed` will not find this log line.

## d. Error codes

Every code in `apps/server/app/constants/error_codes.py`'s `ErrorCode` enum, with its HTTP
status, when it fires, and whether it reaches Sentry. Only an unexpected exception that reaches
the outermost handler (`SERVER_INTERNAL_ERROR`, the catch-all `Exception` handler) is genuinely
unhandled in Sentry's sense; every other code is answered by one of the application's own
exception handlers or middleware guards, which return a response directly rather than letting the
exception propagate, so the SDK's automatic instrumentation never sees it and no event is sent.

| Code                                | HTTP status | Fires when                                                                                                                                                                  | Reaches Sentry                                                                                                                                                   |
| ----------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AUTH_ADMIN_REQUIRED`               | 403         | `require_admin` rejects a signed-in non-admin user                                                                                                                          | No                                                                                                                                                               |
| `AUTH_INVALID_CREDENTIALS`          | 401         | Login with an unknown email or wrong password (same code for both, timing-equalized)                                                                                        | No                                                                                                                                                               |
| `AUTH_REQUIRED`                     | 401         | A protected route is called with no usable session cookie                                                                                                                   | No                                                                                                                                                               |
| `AUTH_SESSION_EXPIRED`              | 401         | The session cookie names a session past its expiry                                                                                                                          | No                                                                                                                                                               |
| `AUTH_EMAIL_ALREADY_REGISTERED`     | 409         | Registration is attempted for an address an account already uses                                                                                                            | No                                                                                                                                                               |
| `AUTH_RESET_TOKEN_INVALID`          | 400         | A password-reset token is unknown, already used, expired, or superseded                                                                                                     | No                                                                                                                                                               |
| `BILLING_NO_ACCOUNT`                | 400         | The billing portal is requested by a user with no Stripe customer yet                                                                                                       | No                                                                                                                                                               |
| `BILLING_NOT_CONFIGURED`            | 503         | Checkout or the portal is called on a deployment with no `STRIPE_SECRET_KEY`                                                                                                | No                                                                                                                                                               |
| `BILLING_WEBHOOK_MISCONFIGURED`     | 400         | A webhook delivery arrives without a `Stripe-Signature` header, or `STRIPE_WEBHOOK_SECRET` is unset                                                                         | No                                                                                                                                                               |
| `BILLING_WEBHOOK_INVALID_SIGNATURE` | 400         | A webhook delivery's signature does not verify against the signing secret                                                                                                   | No                                                                                                                                                               |
| `BILLING_WEBHOOK_IN_PROGRESS`       | 409         | A redelivery meets another delivery's claim on the same event that is younger than ten minutes                                                                              | No                                                                                                                                                               |
| `BILLING_WEBHOOK_PROCESSING_FAILED` | 500         | A verified webhook's handler raised; the event is marked `failed` in the ledger so Stripe redelivers it                                                                     | No (logged as `billing_webhook_event_failed`, but the handler answers a response rather than letting the exception escape)                                       |
| `CSRF_HEADER_MISSING`               | 403         | A state-changing request arrives without `X-Requested-With`                                                                                                                 | No                                                                                                                                                               |
| `IDEMPOTENCY_KEY_IN_PROGRESS`       | 409         | Another request holding the same `Idempotency-Key` is still running                                                                                                         | No                                                                                                                                                               |
| `IDEMPOTENCY_KEY_REUSED`            | 422         | An `Idempotency-Key` is reused for a different method, path, or body                                                                                                        | No                                                                                                                                                               |
| `INPUT_PAYLOAD_TOO_LARGE`           | 413         | The request body exceeds the 100 KB limit, rejected before the route runs                                                                                                   | No                                                                                                                                                               |
| `INPUT_VALIDATION_ERROR`            | 400         | The request body fails Pydantic schema validation, or a bad `Idempotency-Key`                                                                                               | No                                                                                                                                                               |
| `RATE_LIMIT_EXCEEDED`               | 429         | The client exceeds one of the two rate-limit buckets                                                                                                                        | No                                                                                                                                                               |
| `ROUTING_METHOD_NOT_ALLOWED`        | 405         | The path exists but not for the request's method                                                                                                                            | No                                                                                                                                                               |
| `ROUTING_NOT_FOUND`                 | 404         | No route matches the request path                                                                                                                                           | No                                                                                                                                                               |
| `SERVER_DATABASE_UNAVAILABLE`       | 503         | Postgres cannot be reached while handling the request (a connection-level `OperationalError`, a lost-connection `DBAPIError`, or the idempotency middleware's own DB check) | No (logged as `request_database_unavailable` or `idempotency_database_unavailable`, but the handler answers a response rather than letting the exception escape) |
| `SERVER_INTERNAL_ERROR`             | 500         | An exception reaches the outermost `Exception` handler, or an `HTTPException`/`DBAPIError` maps to no other code                                                            | **Yes** - this is the one path Sentry's FastAPI integration captures, from outside the handler that answers the response                                         |
| `SERVER_RATE_LIMIT_UNAVAILABLE`     | 503         | Redis is unreachable in production, so an auth route fails closed rather than open                                                                                          | No                                                                                                                                                               |
| `SERVER_REQUEST_TIMEOUT`            | 408         | The handler runs past the 30-second timeout                                                                                                                                 | No                                                                                                                                                               |
| `UPLOADS_STORAGE_UNCONFIGURED`      | 503         | `POST /v1/uploads` is called on a deployment with no R2 bucket configured                                                                                                   | No                                                                                                                                                               |

Every code above is raised somewhere in the codebase; none is defined but dead, and none is raised
from a call site the enum does not name.

## e. Sentry: server and browser

### Server (`apps/server/app/clients/sentry.py`)

- **Init condition.** `initialize_sentry` starts the SDK only when `settings.sentry_dsn` is set
  and non-blank; otherwise it logs `error_reporting_disabled` once and clears any client an
  earlier application in the process may have set, so a process without a DSN never reports
  through someone else's configuration.
- **Options.** `send_default_pii=False` and `include_local_variables=False` always, regardless of
  environment; the latter exists specifically because a frame's locals would include the raw ASGI
  scope, whose headers carry the session cookie and any `Authorization` value verbatim.
- **Tags.** `tag_sentry_request` sets the `request_id` tag from `RequestContextMiddleware` on
  every request.
- **User identity.** `identify_sentry_user` is called from
  `apps/server/app/dependencies/current_user.py` once a session resolves to a user, and sets only
  `{"id": user_id}` - never the email.
- **Scrubbing (`before_send=scrub_sentry_event`).** Before an event leaves the process it: drops
  `request.cookies`, `request.data` (the body), and `request.query_string` outright; strips the
  query string from `request.url`; drops any header in `{authorization, cookie, set-cookie,
proxy-authorization}` (case-insensitively) from `request.headers`; strips the query string from
  every string value inside every breadcrumb's `data`; and keeps only the `id` field of
  `event.user`, dropping anything else the SDK might have attached.

### Browser (`apps/client/web/shared/services/buildSentryOptions.ts`, used by both

`sentry.client.config.ts` and `sentry.server.config.ts`)

- **Init condition.** `enabled: Boolean(sentryDsn)` - the SDK is fully disabled without a DSN, on
  both the browser and the Nitro server side, from the same shared options builder so the two
  sides cannot drift.
- **`sendDefaultPii: false`** always, which for the browser SDK means the visitor's IP address
  and cookies are not attached by default.
- **`tracesSampleRate: 0`** - performance tracing is off.
- **Scrubbing.** `beforeSend` (`stripEventQuery`) removes `query_string` and strips the query
  string from the event's request URL; `beforeBreadcrumb` (`stripBreadcrumbQueries`) strips the
  query string from every value in a breadcrumb's `data`. Both exist because the reset-password
  page's URL carries a live token in its query string.
- **Request-ID tag.** `apps/client/web/server/middleware/requestId.ts` sets the `request_id` tag
  on the Nitro-side isolation scope for every page request, matching the server's tag so an error
  on either side of one request joins the same logs.

## f. Outbound-call telemetry (`with_client_telemetry`)

Every provider call in `apps/server/app/clients/` runs through
`apps/server/app/clients/telemetry.py::with_client_telemetry`, which logs the provider, the
operation, the duration in milliseconds, and the outcome, and bounds the call with a timeout.
This is the one place in the application with a broad `except Exception`, and it always re-raises
after logging, so a provider failure is visible rather than silently absorbed (R-344).

| Provider  | Operation                 | Client                                                                           | Timeout |
| --------- | ------------------------- | -------------------------------------------------------------------------------- | ------- |
| `resend`  | `send_email`              | `apps/server/app/clients/resend.py::ResendEmailClient.send_email`                | 10.0 s  |
| `posthog` | `capture`                 | `apps/server/app/clients/analytics.py::AnalyticsClient.track_event`              | 5.0 s   |
| `r2`      | `presign_upload`          | `apps/server/app/clients/r2.py::R2Client.presign_upload`                         | 10.0 s  |
| `stripe`  | `create_checkout_session` | `apps/server/app/clients/stripe.py::StripeBillingClient.create_checkout_session` | 10.0 s  |
| `stripe`  | `create_portal_session`   | `apps/server/app/clients/stripe.py::StripeBillingClient.create_portal_session`   | 10.0 s  |

Each call also forwards the bound request ID as an `X-Request-Id` header when one is set (see
Request IDs above), except PostHog's capture, which reads it back out to attach as an event
property rather than send it as an HTTP header, and R2's presign, which is a local signature
computation that touches the network only if boto3's own connect/read timeouts (also 10.0 s) are
exceeded reaching R2 to validate credentials. Stripe's SDK is configured with the same ten-second
timeout and zero automatic retries, so `with_client_telemetry`'s bound is the only one in play; a
failed checkout or portal call releases the idempotency claim in front of it so the client's retry
runs again.

PostHog's `capture` only enqueues: the SDK uploads batches later from its own consumer thread,
outside `with_client_telemetry`, retrying a failed batch up to `POSTHOG_MAX_RETRIES` (3) times
with backoff. The SDK's `on_error` callback, `log_upload_failure`, logs a batch it gave up on as
`client_call_failed` with `provider=posthog`, `operation=upload`, `outcome=failure`, and the batch
size. No duration is logged for an upload, because the SDK does not report one.

## g. Health and readiness endpoints

| Service | Liveness                                                                         | Readiness                       | Checks                                                                                                                              |
| ------- | -------------------------------------------------------------------------------- | ------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| API     | `GET /health`                                                                    | `GET /health/ready`             | Readiness runs `SELECT 1` against Postgres with a 2-second timeout; liveness touches nothing                                        |
| Worker  | `GET /health` (on `WORKER_PORT` when set, else the platform's `PORT`, else 3002) | `GET /health/ready` (same port) | Readiness runs `SELECT 1` against Postgres and a Redis `PING`, concurrently, each with a 2-second timeout; liveness touches nothing |
| Web     | `GET /api/health`                                                                | none                            | Answers `{ status: 'ok' }` from the Nuxt server alone; it never calls the backend, so a backend outage cannot fail this probe       |

All three are registered ahead of the application's own routes (R-345). The API's and worker's
readiness probes both answer 503 with a body naming which dependency failed (`db`/`redis`
`"disconnected"`) rather than a bare failure, so an operator polling the endpoint sees which
dependency is down. The Docker `HEALTHCHECK` in each of `apps/server/Dockerfile`,
`apps/server/Dockerfile.worker`, and `apps/client/web/Dockerfile` calls the liveness endpoint (the
worker's compose service additionally overrides its healthcheck to call `/health/ready`, so
compose treats an unready worker as unhealthy rather than merely alive); `docker-compose.yml`'s
`depends_on: condition: service_healthy` clauses are what make `docker compose up --wait` block
until every container reports healthy.

**Railway.** Each of the three services' Railway configuration file names the same endpoints as
its `healthcheckPath`: `apps/server/railway.api.toml` points at `/health` (liveness, so a Postgres
outage or a Neon cold start never fails a deploy that only changed code, since the pre-deploy
migration has already proven Postgres answers); `apps/server/railway.worker.toml` points at
`/health/ready`, served on the `PORT` Railway injects because `WORKER_PORT` is left unset there;
`apps/client/web/railway.toml` points at `/api/health`. All three set `healthcheckTimeout = 120`
and `restartPolicyType = "ON_FAILURE"` with `restartPolicyMaxRetries = 10`.

**The smoke suite.** `e2e/smoke/services.smoke.ts` (run by `pnpm smoke`, and by the `e2e` CI job
against the compose stack) asks every one of these endpoints in turn, plus the landing page, and
answers only on their literal shape: `{ status: 'ok' }` for a liveness or the web's health route,
and a readiness body matching `{ status: 'ok' }` for the API's and the worker's `/health/ready`.
It reads no data and writes none, so it is safe to run against any deployment.

## How to keep this current

Update this document in the same task that adds, renames, or removes an analytics event, a log
event, an error code, or a telemetry field. A new event or code with no row here, or a row that no
longer matches a renamed or removed call site, is the kind of drift this document exists to
prevent.
