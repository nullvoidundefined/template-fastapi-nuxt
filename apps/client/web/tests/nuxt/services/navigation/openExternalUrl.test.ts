/**
 * Tests for the app's one cross-origin navigation (spec: B-50, US-BILLING).
 *
 * `openExternalUrl` sends the browser wherever the backend's billing answer points, so it refuses
 * anything but `https:`, with `http:` allowed only on localhost, where the end-to-end stack's
 * stripe-mock answers. A refusal throws, which the billing buttons show as an error, and the
 * browser never leaves. `window.location.assign` is replaced by a spy, because happy-dom cannot
 * follow a navigation to another origin; what is asserted is whether it was asked to.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';

import { openExternalUrl } from '~/services/navigation/openExternalUrl';

/** Replace the browser's navigation with a spy and return it. */
function spyOnNavigation() {
    return vi.spyOn(window.location, 'assign').mockImplementation(() => undefined);
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('openExternalUrl', () => {
    it.each([
        'https://checkout.stripe.com/c/pay/cs_test_1',
        'https://billing.stripe.com/p/session/test_1',
        'http://localhost:12111/checkout/cs_test_1',
    ])('leaves for %s', (url) => {
        const navigation = spyOnNavigation();

        openExternalUrl(url);

        expect(navigation).toHaveBeenCalledWith(url);
    });

    it.each([
        'http://checkout.stripe.com/c/pay/cs_test_1',
        'http://localhost.example.test/checkout',
        'javascript:alert(document.cookie)',
        'data:text/html,<script>alert(1)</script>',
        'ftp://files.example.test/checkout',
        '/relative/path',
        'not a url',
    ])('refuses %s and stays on the page', (url) => {
        const navigation = spyOnNavigation();

        expect(() => openExternalUrl(url)).toThrow(Error);
        expect(navigation).not.toHaveBeenCalled();
    });
});
