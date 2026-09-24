# Auth User Stories

## US-AUTH-003: A signed-out visitor cannot reach a signed-in page

**As** a person using an application built from this template
**I want to** be sent to the sign-in page whenever I am not signed in, and kept out of the sign-in page when I am
**So that** the account the server already enforces is enforced by the pages as well, on a first load and on every navigation after it

**Acceptance criteria:**

- [x] A signed-out browser asking for `/dashboard` lands on `/login`, whether it arrives by a full page load or by a client-side navigation (spec B-12).
- [x] A session that expired while a tab sat open redirects on the next navigation rather than after the cache goes stale: the session query revalidates on every mount instead of trusting a cached success. The test populates the cache with a valid session first, so it exercises revalidation rather than an empty cache.
- [x] A backend outage is not treated as a sign-out. Only the status the backend actually answers with for an absent or expired session sends anyone to `/login`.
- [x] A signed-in browser asking for `/login` or for `/register` is sent to `/dashboard`, both pages asserted, since a redirect applied to one and not the other is the likely mistake (spec B-45).
- [x] The protected layout renders nothing until the session resolves, so a protected page never paints content for a visitor who turns out to be signed out.
- [x] The Nitro gate is a presence check only: it never calls the backend, never parses the cookie, skips `/api/**` so a proxied call gets the backend's own 401 rather than a 302 to an HTML page, and never gates `/login` itself.
- [x] Signing out removes the session from the query cache rather than invalidating it, so nothing refetches `GET /v1/auth/me` with a cookie that has just been cleared.
- [x] Two concurrent server-side renders for two signed-in people each reach FastAPI with only their own cookie and their own address, neither is counted in the rate-limit bucket of the Nuxt server's own address, and each rendered page shows its own user (spec B-52).
- [x] The browser's call reaches the backend with its query string intact, the `Set-Cookie` a sign-in answers with reaches the browser, and one request ID is shared by the page response and the backend call, for a missing and for an invalid inbound value (R-341).

**E2E test:** `e2e/authPages.spec.ts`
**Ticket:** IAN-328

## US-AUTH-004: Register, log in, and change a password through the pages

**As** a person using an application built from this template
**I want to** register, log in, see a field-level error beside the field that caused it, and change my password from the dashboard
**So that** the account lifecycle the server already exposes is something I can actually use through a page, not only through a direct request

**Acceptance criteria:**

- [x] The register and login pages submit through the credentials form, and an invalid email or a rejected password shows its error beside the offending input rather than in a page-level banner, driven by the server's real `INPUT_VALIDATION_ERROR` response rather than by browser-native validation or a hardcoded string (spec B-38).
- [x] Every field error is associated with its input through `aria-describedby`, not merely positioned near it, so a screen reader announces the error when the input receives focus.
- [x] The dashboard's password-change form requires the current password, submits through its own mutation, and shows the result: success clears the form, and a wrong current password shows its error beside that field (spec B-50).
- [x] The ui kit ships Button, Modal, Toast, and TextField, each with a Storybook story, and a coverage test compares the components discovered on disk against the stories Storybook actually indexes, so an added component without a story fails the check rather than being satisfied by an empty or excluded story file (spec B-39).
- [x] A `visual-regression` Playwright project snapshots the ui kit and runs in CI, so a rendering change without an updated baseline fails the job (spec B-39, B-48).
- [x] `prefers-reduced-motion: reduce` sets `animation: none` on the components that animate, rather than a shortened duration, and this is asserted rather than assumed (spec B-48).
- [x] The register, login, and password-change forms are each keyboard-operable end to end and pass the same accessibility checks as the rest of the shared conventions' 100 Lighthouse score.

**E2E test:** `e2e/authPages.spec.ts`
**Ticket:** IAN-328
