import type { CurrentUser } from '~/types/currentUser';

/**
 * What asking the backend who is signed in can turn out to mean.
 *
 * `signedOut` and `unavailable` are kept apart deliberately: only the first is a reason to send
 * someone to the sign-in page, and collapsing them signs people out whenever the API is down.
 */
export type SessionOutcome =
    | { state: 'signedIn'; user: CurrentUser }
    | { state: 'signedOut' }
    | { state: 'unavailable'; status: number };
