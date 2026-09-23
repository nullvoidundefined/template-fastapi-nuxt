# Slice 03: Auth

Spec: `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md` (acceptance criteria B-10 to B-13, B-31, B-32, B-38, B-39, B-45, B-48, B-50 in part, B-52)
Status: drafted 2026-09-23, revised after the pre-Gate-1 review, awaiting Gate 1
Tracker: IAN-314, with one child ticket per pull request
Estimate: 6.5 hours of agent time across four pull requests. The spec's figure is 5 hours; the pre-Gate-1 review found three pieces of work no pull request had been given, and the revision below carries them. History also says to multiply by 1.6: every ticket in slice 02 ran between 1.6 and 1.9 times its estimate, and the gap was review rounds and the test updates a new guard forces on an existing suite.

## Purpose

Slice 02 left the application able to store a user, fail in one shape, and refuse a request it should not serve. Nothing signs in. This slice adds the account lifecycle on both sides: the session store and the primitives that protect a password, the five endpoints that create and end a session, the proxy and gate that let a Nuxt page depend on one, and the pages a person actually uses.

It is the largest slice in the plan and the first that spans both sides of the stack, which is why the pull request split below is a real decision rather than a formality. The seam is the API contract: the first two pull requests make the backend answer, the last two make the frontend consume it.

## What changes about how this slice is built

Two process changes from slice 02's retrospective.

**Four pull requests instead of five.** The fixed cost of a pull request here is roughly 30 minutes before any code. Slice 02 ran five and its first was configuration-only, paying full price for it.

**The plan is reviewed before Gate 1, not after.** Slice 02's plan was reviewed after it merged, so its errors became ticket corrections rediscovered during the build. This document went to Codex first, and that review changed it substantially: it found a criterion this plan had misread, three pieces of work no pull request owned, an ordering problem between the last two pull requests, and a concurrency hole in the password change. Those are recorded inline below rather than as a list of corrections, because the point of reviewing a plan early is that its output is a better plan rather than a longer ticket.

Otherwise unchanged: Codex authors every test before the implementation exists (R-907), the implementation runs red, green, refactor under the harness lock (R-412), Codex reviews each diff before merge (R-517), the owner approves and merges each pull request (Gate 2), and each writes its `docs/prs/` document, feature row, and story (R-607).

## Scope notes

**Two of the four rate-limited auth paths become real here.** `/v1/auth/login` and `/v1/auth/register` get handlers; `/v1/auth/forgot-password` and `/v1/auth/reset-password` are slice 04. The limiter runs before routing, so a request to a path with no handler is still counted, and slice 02's test-only router stays mounted for the two that do not exist yet. Do not delete it wholesale.

**`users.role` is slice 05**, so `GET /auth/me` answers the ID and email and nothing else. B-32 says the role joins later.

**The dashboard's billing buttons are slice 06.** B-50 spans both slices; this one delivers the profile form.

## The decision the review says to make first

B-11 requires that an unknown email still runs a bcrypt comparison, and B-13 requires that a password change signs out every other session. Those two meet in a race that neither criterion names, and that a transaction around each one separately does not close.

A login can read the user, verify the old password, and be descheduled. A password change can then commit its new hash and delete every other session. The login then inserts a live session built on credentials that are no longer valid. The result is a session that survives a password change made specifically to revoke it, which is the case a password change exists for.

The plan's answer is that both flows take a row lock on the user before verifying anything: `SELECT ... FOR UPDATE` on the `users` row inside the request transaction that `get_connection` already opens, in login, in the password change, and in any later flow that verifies a password. That serializes them per user and costs nothing when there is no contention. PR 1 provides it, because both callers are in PR 2 and a primitive shared by two callers belongs to the pull request before them.

This is the single change the pre-Gate-1 review most wanted, and it is why PR 1's scope grew.

## Execution record

| PR  | Concern                                                  | Ticket  | PR number | Merged | Scope change                                                                                                                                                                                                                                                                                                   |
| --- | -------------------------------------------------------- | ------- | --------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `user_sessions`, the security primitives, the dependency | IAN-315 | #31       |        | The dummy-hash test became structural rather than value-based: Codex showed that asserting the dummy password is rejected also passes against a short-circuit that never runs bcrypt, so `resolve_comparison_hash` was extracted as a pure function and an AST test pins that the verifier has no conditional. |
| 2   | The five auth endpoints and the field-error contract     | IAN-320 | #32       |        | A slice 02 rate-limit test asserted 404 from `/v1/auth/login` as a proxy for the limiter serving a request, which only held while login had no handler. It now asserts on the refusal codes, because the route answers 503 for an unrelated reason and no status can tell the two apart.                       |
| 3   | The proxy, the query layer, and the auth gate            | pending | pending   |        |                                                                                                                                                                                                                                                                                                                |
| 4   | The ui kit and the forms                                 | pending | pending   |        |                                                                                                                                                                                                                                                                                                                |

IAN-306 and IAN-312, the two follow-ups slice 02 left, are separate maintenance work rather than a prerequisite for any of this. They are worth doing as a `bundle` pull request before PR 1 because IAN-312 makes a stopped Docker daemon produce a green run instead of a red one, which cost time twice in slice 02, but they are approved on their own merits and not as part of this slice.

## PRs

### PR 1: `user_sessions`, the security primitives, and the session dependency

**Context:** Slice 02 shipped `users`, the per-request connection at `scope="function"`, and the error envelope. Nothing hashes a password and nothing reads a cookie.

**Problem:** Every endpoint in PR 2 needs the same primitives, and they are the part of this slice where a mistake is a security defect rather than a bug. Building them inside the first endpoint means the second refactors them.

**Approach:** Add the `user_sessions` migration: `id`, `user_id` referencing `users` with `ON DELETE CASCADE`, `token_hash` unique, `expires_at`, `created_at`, `last_seen_at`, and an index on `expires_at` for the cleanup job in slice 08. No `set_updated_at` trigger, because a session has no `updated_at`.

Add `app/core/security.py`. `hash_password` and `verify_password` run bcrypt at cost 12 inside `asyncio.to_thread`, because a quarter-second on the event loop blocks every other request in the process. `verify_password` compares against a module-level dummy hash when the stored hash is `None`, so the unknown-email path costs what the wrong-password path costs. `generate_session_token` returns `secrets.token_urlsafe(32)` and its SHA-256 together, so a caller cannot store the raw one by accident.

Add `app/repositories/users.py` and `app/repositories/user_sessions.py`, both taking the connection. `users.py` carries `lock_user_for_update`, the `SELECT ... FOR UPDATE` the section above requires, and every lookup normalizes the email by trimming and lowercasing it, not only the insert: a lookup that uses the submitted case fails to find an account that exists.

`user_sessions.py` writes `last_seen_at` through a conditional `UPDATE ... WHERE last_seen_at < now() - interval '5 minutes'`, which the data model caps at once per five minutes per session. A read-then-write decision lets simultaneous requests all write.

Add `app/dependencies/current_user.py`. It returns a typed result carrying the user and the id of the session that authenticated it, because the password change in PR 2 has to preserve the caller's own session and cannot do that from the user alone. It distinguishes no cookie, an unknown token, and an expired session, answering `AUTH_REQUIRED` for the first two and `AUTH_SESSION_EXPIRED` for the third, which a query filtering on `expires_at > now()` alone cannot do. A second, non-raising resolver serves logout, which B-31 requires to answer 204 with no session at all.

No route is added here. The tests are unit and integration tests of the primitives, where a cryptographic property can be asserted directly rather than through a route.

**Contents:** `migrations/versions/<rev>_create_user_sessions.py`, the table in `app/db/tables.py`, `app/core/security.py`, `app/repositories/users.py`, `app/repositories/user_sessions.py`, `app/dependencies/current_user.py`, `app/constants/session.py`, tests, the feature row and `US-AUTH-001`.

**Tests:** The revision is reversible. `hash_password` produces a hash `verify_password` accepts, a different hash for the same password on a second call, and one whose stored cost is 12, asserted by reading the cost out of the hash rather than trusting the constant. `verify_password` returns False for a wrong password, and for a `None` stored hash it returns False **even when the candidate is the dummy password itself**, which is the assertion that proves the comparison really ran against the dummy rather than being short-circuited. A separate test proves hashing and verification run off the event loop. No timing assertion: the first draft proposed one, and the review pointed out that a sleep, a slow branch, or a synchronous bcrypt all satisfy a duration floor, so it measures the wrong thing and goes flaky on CI besides.

`generate_session_token` returns a hash equal to the SHA-256 of its raw token, and the raw token is never what the repository stores. The dependency answers `AUTH_REQUIRED` with no cookie and with an unknown token, `AUTH_SESSION_EXPIRED` past `expires_at`, and the user plus the session id for a live one. `lock_user_for_update` serializes two concurrent transactions on one user, asserted by starting both and observing the second block until the first commits.

**Review focus:** That no path stores or logs a raw token, that bcrypt never runs on the event loop, and that the dummy-hash test asserts rejection of the dummy password rather than a duration.

**Size:** About 11 files and 500 lines.

**Estimate:** 90 minutes.

### PR 2: The five auth endpoints and the field-error contract

**Context:** PR 1 has landed. The primitives exist and nothing calls them.

**Problem:** B-10, B-11, B-13, B-31 and B-32 are one concern, the session lifecycle. They also carry a contract change that B-38 depends on two pull requests later, and which has to be settled here because it changes `openapi.yaml`.

**The field-error contract.** B-38 requires a validation error to show beside the input it names. The envelope cannot express that today: `handle_request_validation_error` joins the field errors into one string through `summarize_field_errors`, and `ErrorResponse.error` is documented as never parsed by clients. So `ErrorResponse` gains an optional structured field, a list of `{ field, message }`, populated only for `INPUT_VALIDATION_ERROR`. The human-readable `error` string stays exactly as it is, so nothing that reads it breaks. Without this, PR 4 has to parse a prose message or reopen a finished API contract.

**Approach:** Add `app/routers/auth.py` with `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/auth/me`, and `PATCH /v1/auth/me`, and `app/schemas/auth.py`. Registration, login, and the password change are multi-step business operations, so they live in `app/services/auth/` with the routers calling them, which is where the Python track puts orchestration.

Registration normalizes the email, relies on slice 02's unique index on `lower(email)`, and catches `IntegrityError` whose `orig.sqlstate` is `23505` **around the insert**, not around a preceding select, since a select-then-insert has a race the index exists to close. `AUTH_EMAIL_ALREADY_REGISTERED` joins the error registry, which does not carry it yet.

Login locks the user row, runs `verify_password` whether or not the user was found, answers `AUTH_INVALID_CREDENTIALS` in both cases, and on success deletes that user's expired sessions while leaving live ones, in the same transaction as the insert.

`PATCH /auth/me` locks the user row, requires the current password, and deletes every session except the one the caller is using, which PR 1's dependency identifies.

Cookie attributes come from one helper: `httpOnly`, `SameSite=Lax`, `Secure` outside local development, `max_age` from the 7-day lifetime, `path=/`.

**Contents:** `app/routers/auth.py`, `app/schemas/auth.py`, `app/services/auth/` (register, login, change password), the cookie helper, `AUTH_EMAIL_ALREADY_REGISTERED` in `app/constants/error_codes.py`, the `ErrorResponse` field-error addition and the handler change, the router registration, the regenerated `openapi.yaml` and `schemas.ts`, tests, the feature row and `US-AUTH-002`. Also the missing `Access-Control-Expose-Headers` test that slice 02 shipped without, since this pull request touches `main.py` anyway.

**Tests:** These need their own integration fixtures with reachable Postgres and Redis and an HTTPS origin, because the shared fixtures point at closed ports and a `Secure` cookie is not replayed over plain HTTP, so a revocation test could pass having never sent the cookie at all. Every revocation test first proves the cookie authenticates.

B-10: a bcrypt hash at cost 12, a lowercased email, a mixed-case duplicate answering 409 with `AUTH_EMAIL_ALREADY_REGISTERED`, each cookie attribute asserted separately including `Secure` under production and absent under local development, and the issued cookie's SHA-256 equal to the stored `token_hash`. B-11: a wrong password and an unknown email answer the same code; a correct login writes a row and sets the cookie; a login with one expired and one live session removes exactly the expired one; and a mixed-case, whitespace-padded email logs in successfully. B-13: the change requires the current password, the old password then fails and the new one works, another browser's cookie fails, and the caller's still works. B-31: 204 with and without a session, the row deleted, and the cookie cleared, asserted on the `Set-Cookie` expiry rather than only on a later rejection. B-32: `{ data: user }` with id and email, no password hash, 401 without a session.

The race: a login and a password change on one user, run concurrently with a barrier so they genuinely overlap, must not leave a session created from the old password. Without the row lock this test fails.

Rate limiting: login and register are now real routes and the existing limiter tests must still pass against them, with `/v1/auth/me` still outside the auth bucket. The test-only router stays for the two paths slice 04 adds.

**Review focus:** That the duplicate catch wraps the insert, that the password change excludes the caller's own session rather than signing everyone out, and that the race test actually overlaps rather than merely launching two coroutines.

**Size:** About 14 files and 600 lines.

**Estimate:** 110 minutes.

### PR 3: The proxy, the query layer, and the auth gate

**Context:** PRs 1 and 2 have landed and the API answers. Slice 01 already shipped `app/api/apiClient.ts`, `app/composables/useApiClient.ts` and `shared/services/resolveClientAddress.ts`, so the client factory, its per-request memoization, the CSRF base header and the forwarded-header filtering exist. The first draft of this plan listed them as work to do, which the review corrected.

**Problem:** What does not exist is everything between that client and a page: `@tanstack/vue-query` is not a dependency, there is no query plugin, no per-request `QueryClient`, no route wrappers in `app/api/`, and nothing that turns openapi-fetch's `{ error, response }` return into a failed query, since it does not throw on an HTTP error. Without that layer the gate has nothing to read a session through.

**Approach:** Add the query layer first: `@tanstack/vue-query` (R-331 justification: no existing module provides request caching with SSR hydration), a plugin creating one `QueryClient` per request, and hydration so a server-rendered page does not refetch. Add one wrapper per backend route in `app/api/`, each taking the client as its first parameter, which is what makes its types come from the OpenAPI document. Add a shared helper that raises on `{ error }` so a failed request becomes a failed query rather than a resolved one holding an error.

Add the proxy `server/api/[...path].ts`, forwarding with h3's `proxyRequest`, preserving the query string, mapping `/api/v1/...` to `/v1/...`, passing cookies and the CSRF header through, propagating `Set-Cookie` back, and rewriting `X-Forwarded-For` through `resolveClientAddress` so the limiter keys on the address the edge appended.

Add the Nitro request-ID middleware carried on the Later list since slice 01. It mints an ID when a page request carries none and must put it where the existing server-side client reads its request headers, not only on the response: setting the response header alone leaves FastAPI minting a different one, and the page and its API calls then correlate to nothing.

Add the three-part gate: `server/middleware/sessionCookieGate.ts` for a presence check on a full page request, `app/middleware/requireSession.ts` for client-side navigation and expiry, and `app/layouts/protected.vue` rendering only once the session resolves. Add `redirectIfSession` for B-45, on `/login` **and** `/register`, and the `auth` layout the frontend map requires. Specify that the session query revalidates on navigation rather than trusting a cached success, or an expired session navigates freely until the cache goes stale, and that the logout mutation's `onSuccess` removes the session query, which the Nuxt track requires and which no pull request had been given.

This pull request also ships minimal permanent `/login`, `/register` and `/dashboard` pages, wired to the real middleware and layout. They are not placeholders to be replaced: PR 4 adds the kit and the forms to them. Without them PR 3's own acceptance tests have no page to redirect to, which the review caught as an ordering problem between these two pull requests.

**Contents:** `@tanstack/vue-query` in `apps/client/web/package.json`, `app/plugins/queryClient.ts`, `app/api/` route wrappers and the error helper, `server/api/[...path].ts`, `server/middleware/sessionCookieGate.ts`, `server/middleware/requestId.ts`, `app/middleware/requireSession.ts`, `app/middleware/redirectIfSession.ts`, `app/layouts/protected.vue`, `app/layouts/auth.vue`, `app/composables/useSessionQuery.ts`, the logout mutation, the three pages, tests, the feature row and `US-AUTH-003`.

**Tests:** B-12 as an end-to-end spec: a signed-out browser loading `/dashboard` lands on `/login`, and a client-side navigation with an expired session does too, with the cache first populated by a valid session so the test exercises revalidation rather than an empty cache. B-45 on both `/login` and `/register`.

B-52 is the one to design rather than write. The criterion is that two concurrent server-side renders for two signed-in users each reach FastAPI with only their own cookie and their own address, **and that neither is counted in the rate-limit bucket of Nitro's address**. The first draft of this plan said "neither counted in the other's bucket", which is a different and weaker claim; the review caught it. So the test drives the real Nitro-to-uvicorn path, uses a barrier to force genuine overlap, asserts each user's own bucket moved and Nitro's did not, and asserts each rendered page shows its own user, since forwarding the right cookie proves nothing if a shared query cache then serves the wrong session.

The proxy gets its own tests: the query string survives, `Set-Cookie` propagates, and one request ID is shared by the page response and the backend request, for a missing and an invalid inbound value.

**Review focus:** That no client or `QueryClient` is constructed at module scope, including inside a composable imported at module scope, and that the request ID reaches the outgoing request headers rather than only the response.

**Size:** About 18 files and 550 lines.

**Estimate:** 110 minutes.

### PR 4: The ui kit and the forms

**Context:** The gate works and the three pages render minimally.

**Problem:** B-39 requires a story per `components/ui/` component and a visual-regression project that fails on an unreviewed rendering change, and the spec fixes what the kit contains: Button, Modal and Toast on Reka UI, with `ToastRegion` driven by `useToast()` and a modal stack driven by `useModal()` carrying open, close, `closeAllModals` and a `preventClose` option in a `useState` store. The first draft of this plan invented a different five-component list and omitted Modal and Toast entirely.

**Approach:** Build the kit the spec names, plus the form components the three pages need: an input with its label and error, and a form field wrapper. Each component gets a story. The `visual-regression` Playwright project snapshots them and runs in CI.

Then the forms: register, login, and the dashboard's profile form. B-38's field error uses the structured field errors PR 2 added, bound to its input with `aria-describedby` rather than merely rendered nearby.

Accessibility is part of this pull request rather than a follow-up: the shared conventions require a 100 Lighthouse accessibility score, and B-48 brings the reduced-motion requirement, so `prefers-reduced-motion: reduce` uses `animation: none` rather than a shortened duration, and that is asserted rather than assumed.

**Contents:** `app/components/ui/` with one folder per component and a story each, `app/composables/useToast.ts`, `app/composables/useModal.ts`, the forms on the three existing pages, the Storybook configuration, the `visual-regression` Playwright project and its CI job, tests, the feature row and `US-AUTH-004`.

**Tests:** B-39: the coverage test compares the components discovered recursively on disk against the stories Storybook actually indexes, not against filenames, because an empty story file or one excluded by the configuration satisfies a filename check while rendering nothing. Adding a component without a story must fail it, and changing a rendered component without updating its baseline must fail the snapshot.

B-38: an invalid email shows the field error beside the email input, driven by a real `INPUT_VALIDATION_ERROR` response rather than by browser-native validation or a hardcoded string, either of which would satisfy a purely visual assertion. B-50: the profile form changes the password and shows the result. B-48: reduced motion. Plus the keyboard and screen-reader paths.

**Review focus:** That the story coverage test reads Storybook's index rather than the filesystem alone, and that the field error is associated with its input rather than positioned near it.

**Size:** About 22 files and 600 lines.

**Estimate:** 120 minutes.

## Open questions for Gate 1

1. **The row lock.** `SELECT ... FOR UPDATE` on the user in login and in the password change is the plan's answer to the race described above. It is the conventional fix and it costs nothing uncontended. The alternative is to accept the race, which means a password change does not reliably revoke, and to record that. This is the decision the pre-Gate-1 review most wanted made.
2. **Extending the error envelope.** PR 2 adds an optional structured field-error list to `ErrorResponse`. It is additive and the prose message is unchanged, but it is a contract change reaching `@repo/api-types`, so it is the owner's call rather than an implementation detail.
3. **Four pull requests, split at the API contract, with PR 3 carrying minimal pages.** The alternative is five, splitting the query layer out of PR 3, which is the largest remaining unit. The estimate says PR 3 and PR 4 are both close to two hours, which is at the upper end of reviewable.

## Later list

- **Slice 04, worker startup tests:** no test asserts the worker configures logging at startup or runs its readiness checks concurrently. Carried from slice 01, deferred again because slice 03 does not change the worker.
- **Slice 05, `users.role` in `GET /auth/me`:** B-19 adds it; B-32 already anticipates it.
- **Slice 06, the dashboard's billing buttons:** the other half of B-50.
- **Maintenance, not part of this slice:** IAN-306 and IAN-312, worth a `bundle` pull request before PR 1 but approved on their own merits.
