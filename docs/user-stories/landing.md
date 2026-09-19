# Landing User Stories

## US-LANDING-001: Landing page with links to log in and register

**As** a visitor
**I want to** see what the product is and find the way to log in or create an account
**So that** I can start using it from the first page I land on

**Acceptance criteria:**

- [x] The landing page renders one `<h1>` naming the product (spec B-49).
- [x] It links to `/login` and `/register` by accessible name, and each link navigates to its route (spec B-49).

**E2E test:** `e2e/landing.spec.ts`
**Ticket:** IAN-125
