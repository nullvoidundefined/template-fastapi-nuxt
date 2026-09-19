# Spec: per-request API client and an owner token on idempotency claims

Refs: IAN-146. Branch: `chore/spec-api-client-idempotency`. Changes: `docs/superpowers/specs/2026-09-19-template-fastapi-nuxt-design.md` and `docs/slices/slice-01-walking-skeleton.md`.

## Summary

The review of the agent-governance convention-track corrections (IAN-145, agent-governance PR #75) found three defects that this template's spec shares with the old track text. The spec passed `useRequestFetch()` as openapi-fetch's `fetch` function, which cannot work. The idempotency lease had no owner token, so a slow original request could overwrite or delete the claim that took it over. And nothing said the API client must be created per request, so a module-level client would send one user's cookie on another user's server-side render. None of this code exists yet: the client arrives in slice 01 PR 3 (IAN-126) and the idempotency middleware in slice 05. That makes this the cheapest moment to correct the spec. The pre-merge review of this change found eight more gaps in the same two passages, and they are fixed here too.

## What changed

- **Request path paragraph.** `api/apiClient.ts` exports `createApiClient()`, and `useApiClient()` memoizes one client per Nuxt app instance (one per request on the server). No module-level client exists. `useApiClient()` runs only in setup, and each `app/api/` function takes the client as its first parameter. The client sets `X-Requested-With: XMLHttpRequest` in both environments. The generated paths carry `/v1`, so the browser base URL is `/api` (proxied `/api/<rest>` to `/<rest>`) and the server base URL is `runtimeConfig.apiBaseUrl`. Server-side calls carry the cookie, the `X-Request-Id`, and a single-value `X-Forwarded-For` from `shared/services/resolveClientAddress.ts`, the same function the Nitro proxy uses. The paragraph also states why `useRequestFetch()` is not the `fetch` function.
- **`request_idempotency_keys` row.** A `claim_token` column. Takeover is one `UPDATE ... RETURNING` that also matches method, path, and body hash. A takeover that returns no row re-reads the row and answers 422, 409, or the stored response. Claim, takeover, completion, and release each run in their own short transaction outside the request transaction. Completion and release are scoped to `claim_token = :mine`. The 60-second lease is stated as longer than the 30-second request timeout.
- **New criteria.** B-52 (slice 03): concurrent server-side renders for two users each carry only their own cookie and client address. B-53 (slice 05): a late original request changes nothing after a takeover.
- **Slice table.** Slice 03 names the Nitro proxy and its reuse of `resolveClientAddress`. The slice 01 PR 3 block matches the spec, and its Contents list gains `useApiClient.ts` and `resolveClientAddress.ts`.

## Architectural decisions

- **Chosen: forward the cookie with `useRequestHeaders(['cookie'])` on a per-request client.** **Alternative:** wrap `useRequestFetch()` in an adapter that returns a `Response`. **Why not:** the adapter would re-implement the response parsing openapi-fetch already does, and it would still need to be per request.
- **Chosen: `api/` functions take the client as a parameter.** **Alternative:** each `api/` function calls `useApiClient()`. **Why not:** `useNuxtApp()` throws once an `await` inside a query function has dropped the Nuxt context, and `experimental.asyncContext` is off by default in Nuxt 4.
- **Chosen: `shared/services/resolveClientAddress.ts`, departing from the Nuxt track's `shared/types/`-only listing.** The server-side client in `app/` and the Nitro proxy in `server/` must apply one trust rule. **Alternative:** two copies. **Why not:** two copies of a security rule drift.
- **Chosen: the takeover `WHERE` matches method, path, and body hash.** **Alternative:** a separate mismatch read before the takeover. **Why not:** a read followed by a write is exactly the race the single statement exists to close.

## Testing

A documentation-only change with no code to run. B-52 and B-53 name the tests that slices 03 and 05 write. B-53 fails against an implementation without the token, because a stale completion would change the stored row.

## Codex review

**Reviewer:** Claude subagent (fable). Fallback reason: Codex usage limit reached until 18:00. It used the `codex-pr-review-prompt.md` prompt and verified the library claims against the installed openapi-fetch, nuxt 4.5.2, and FastAPI sources and the PostgreSQL concurrency documentation. It reported eight findings, and all eight are fixed in this PR.

| #   | Severity | Finding                                                                                                                    | Disposition                                                                                                       |
| --- | -------- | -------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 1   | MEDIUM   | Both base URLs added `/v1`, which the generated paths already carry, giving `/v1/v1/...`                                   | Fixed: the browser base is `/api`, the server base is `apiBaseUrl`, and the proxy maps `/api/<rest>` to `/<rest>` |
| 2   | LOW      | Server-side calls dropped `X-Request-Id` (R-341)                                                                           | Fixed: the request ID is in the server-side headers                                                               |
| 3   | LOW      | Nothing set `X-Requested-With`, so every browser `POST` would answer 403 (B-6)                                             | Fixed: a base header in both environments                                                                         |
| 4   | LOW      | `api/` functions calling `useApiClient()` throw after an `await` drops the Nuxt context                                    | Fixed: `useApiClient()` runs in setup, and `api/` functions take the client as a parameter                        |
| 5   | LOW      | A claim inside the request transaction is invisible to other requests until commit                                         | Fixed: claim, takeover, completion, and release each run in their own short transaction                           |
| 6   | LOW      | The response to a takeover that returns no row was unstated                                                                | Fixed: re-read, then 422, 409, or replay                                                                          |
| 7   | LOW      | The takeover could let a request with a different body take over an expired claim (B-40)                                   | Fixed: the takeover `WHERE` matches method, path, and body hash                                                   |
| 8   | LOW      | The shared `X-Forwarded-For` function had no module, the proxy had no slice, and PR 3's Contents omitted `useApiClient.ts` | Fixed: `shared/services/resolveClientAddress.ts`, slice 03 ships the proxy, and PR 3's Contents is updated        |

**Copilot's review** raised one point: the takeover's re-read can find no row when the holder releases its claim just before the takeover, and the spec gave no answer for that case. Fixed: the request retries the initial claim insert once, and B-53 covers the race.

## Reflection

Work started at about 10:09Z, and this document was written at about 10:30Z. I first treated this as three sentence fixes. The review showed that the passages around them were underspecified in the same way. The base URL doubled `/v1`, which only reading FastAPI's OpenAPI export and openapi-fetch's URL builder together revealed. The claim's transaction boundary decides whether the 409 path can fire at all. What I understand now is that a spec paragraph that names a library call has to be checked against that library's contract, not just against how the call sounds.
