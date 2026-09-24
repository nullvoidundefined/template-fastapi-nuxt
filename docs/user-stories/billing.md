# Billing User Stories

## US-BILLING-001: Subscribe through Stripe Checkout

**As** a signed-in person using an application built from this template
**I want to** start a subscription and be sent to Stripe's hosted Checkout page
**So that** I can pay for a plan without the application ever handling my card details

**Acceptance criteria:**

- [x] `POST /v1/billing/checkout` answers the Stripe Checkout URL for the signed-in user, and the Stripe request carries `mode: subscription`, the given `price_id`, `metadata.user_id`, a success URL of `{client_url}/dashboard?checkout=success`, and a cancel URL of `{client_url}/dashboard?checkout=cancelled` (spec B-33).
- [x] The same request repeated with the same `Idempotency-Key` answers the same URL and creates no second Checkout session, and a key first used on checkout is refused on the portal (spec B-33, B-40).
- [x] A `price_id` outside `^price_[A-Za-z0-9]+$`, or any malformed body, answers 400 `INPUT_VALIDATION_ERROR` without calling Stripe (spec B-33, R-406).
- [x] A deployment without `STRIPE_SECRET_KEY` answers 503 `BILLING_NOT_CONFIGURED` rather than failing on its first Stripe call.
- [ ] The dashboard's checkout button redirects to the Checkout URL (spec B-50; the slice 06 client half).

**E2E test:** pending; the slice 06 client half adds it against stripe-mock
**Ticket:** IAN-338

## US-BILLING-002: Manage a subscription in the Stripe billing portal

**As** a subscribed person
**I want to** open Stripe's billing portal from the dashboard
**So that** I can change my plan, update my card, or cancel without the application building those screens

**Acceptance criteria:**

- [x] `POST /v1/billing/portal` answers 400 `BILLING_NO_ACCOUNT` for a user with no Stripe customer, and for a user with one answers the portal URL created with a return URL of `{client_url}/dashboard` (spec B-22).
- [ ] The dashboard's portal button redirects to the portal URL (spec B-50; the slice 06 client half).

**E2E test:** pending; the slice 06 client half adds it against stripe-mock
**Ticket:** IAN-338

## US-BILLING-003: Stripe's webhook keeps the subscription current

**As** the operator of an application built from this template
**I want** Stripe's webhook deliveries verified, applied once each, and retried when they fail
**So that** a user's subscription state in the database always matches Stripe's, however Stripe delivers

**Acceptance criteria:**

- [x] A delivery with a bad signature answers 400 `BILLING_WEBHOOK_INVALID_SIGNATURE`, and one without a `Stripe-Signature` header, or to a deployment without a signing secret, answers 400 `BILLING_WEBHOOK_MISCONFIGURED`; neither writes anything (spec B-20, B-42).
- [x] A verified event outside the five-event allowlist answers 200 and changes no row (spec B-34).
- [x] The same event delivered twice changes `user_subscriptions` once, and `checkout.session.completed` is mapped to its user through `metadata.user_id` (spec B-21).
- [x] Each of the five allowlisted events writes its columns: checkout links the customer and subscription; the three subscription events set the status, plan, period, and cancel flag; `invoice.payment_failed` sets `past_due` (spec B-51).
- [x] A handler exception marks the event `failed` and answers 500 `BILLING_WEBHOOK_PROCESSING_FAILED`; a failed event and a claim older than ten minutes are processed on redelivery (spec B-41, B-42).
- [x] The webhook is exempt from the CSRF guard and from both rate-limit buckets (spec B-6, B-7).

**E2E test:** none; Stripe cannot deliver to the end-to-end stack, so the integration suite `apps/server/tests/integration/routers/billing/test_billing_webhook.py` covers it with signed deliveries
**Ticket:** IAN-338
