/**
 * Sends the browser to another origin, such as Stripe's Checkout or billing portal (spec: B-50).
 *
 * A module of its own so the one cross-origin navigation the app performs has one place to live,
 * and so a component test can observe where the page would have gone.
 */

/** Leave the app for the given absolute URL. */
export function openExternalUrl(url: string): void {
    window.location.assign(url);
}
