/**
 * Sends the browser to another origin, such as Stripe's Checkout or billing portal (spec: B-50).
 *
 * A module of its own so the one cross-origin navigation the app performs has one place to live,
 * and so a component test can observe where the page would have gone. The URL comes from the
 * backend's answer, so it is checked before the browser follows it: only `https:` is followed,
 * and `http:` only on localhost, where the end-to-end stack's stripe-mock answers. Anything else,
 * a `javascript:` URL above all, throws, and the calling component shows the failure instead.
 */

const SECURE_PROTOCOL = 'https:';
const LOCAL_PROTOCOL = 'http:';
const LOCAL_HOSTNAME = 'localhost';

/** Leave the app for the given absolute URL, throwing when it is not a URL the app may follow. */
export function openExternalUrl(url: string): void {
    const { hostname, protocol } = parseAbsoluteUrl(url);
    const isSecure = protocol === SECURE_PROTOCOL;
    const isLocal = protocol === LOCAL_PROTOCOL && hostname === LOCAL_HOSTNAME;
    if (!isSecure && !isLocal) {
        throw new Error(`Refusing to leave the app for a ${protocol} URL`);
    }
    window.location.assign(url);
}

/** Parse the URL with no base, so a relative or malformed one throws rather than resolving. */
function parseAbsoluteUrl(url: string): URL {
    try {
        return new URL(url);
    } catch (failure) {
        throw new Error('Refusing to leave the app for a URL that is not absolute', {
            cause: failure,
        });
    }
}
