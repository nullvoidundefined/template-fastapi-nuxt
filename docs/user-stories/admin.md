# Admin user stories

## US-ADMIN-001: See every account as an administrator

**As** an administrator of an application built from this template
**I want to** see every account with its role and the date it joined
**So that** I can tell who uses the application without querying the database

**Acceptance criteria:**

- [x] A member calling `GET /v1/admin/users` receives 403 `AUTH_ADMIN_REQUIRED`, and an admin receives `{ data, meta: { total, limit, offset } }` whose items carry exactly `id`, `email`, `role`, and `created_at`, never a password hash (spec B-19).
- [x] Every auth response and `GET /v1/auth/me` include the user's `role` (spec B-19).
- [x] `/admin` lists the users for an admin; a member visiting it lands on `/dashboard`, and a signed-out visitor lands on `/login` (spec B-19).

**E2E test:** `e2e/admin.spec.ts`
**Ticket:** IAN-336
