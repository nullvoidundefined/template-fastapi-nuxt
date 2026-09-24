/**
 * Tests for the toast region (spec: slice 03 PR 4, the design spec's "UI kit" line, US-AUTH-004).
 *
 * The region is what a visitor actually meets, so every assertion here is written in the terms a
 * screen reader would use: the region's role and accessible name, the words of each message, the
 * accessible name of each dismiss control. None of them name a component, a class or a test id, so
 * the kit can be restyled or its internals renamed without touching this file, and a region that
 * renders the right markup with the wrong words still fails.
 *
 * Two toasts are on screen in every test because a queue that keeps only the newest message would
 * otherwise pass: a save confirmation arriving while a session warning is up must not silence the
 * warning, and dismissing either one must leave the other alone.
 *
 * The live-region assertion is the one query here that reaches past the accessibility tree into
 * the DOM. It has to: the element Reka announces a new toast through is marked `aria-hidden` (its
 * words are already on screen for sighted visitors), so a role query cannot see it, and asserting
 * only that the text is on screen would pass for a region that never announces anything. Reading
 * the `aria-live` elements' text is the closest a unit test gets to what is spoken.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen, within, fireEvent } from '@testing-library/vue';

import ToastRegion from '~/components/ToastRegion/ToastRegion.vue';

import {
    dismissEveryToastInApp,
    readToastMessages,
    settleUserInterface,
    showToastInApp,
} from '../../uiKitHarness';

const profileSavedMessage = 'Your profile has been saved.';
const sessionExpiringMessage = 'Your session expires in one minute.';

/** The notifications region as the accessibility tree exposes it. */
function readToastRegion(): HTMLElement {
    return screen.getByRole('region', { name: /notification/i });
}

/** The toast carrying the given words, found the way a reader finds it: by what it says. */
function readToastSaying(message: string): HTMLElement {
    const toasts = within(readToastRegion()).getAllByRole('listitem');
    const match = toasts.find(function saysMessage(toast) {
        return (toast.textContent ?? '').includes(message);
    });
    if (match === undefined) {
        throw new Error(`No toast in the region says "${message}".`);
    }
    return match;
}

/** Everything the assistive-technology live regions currently hold, joined for a contains check. */
function readAnnouncedText(): string {
    const liveRegions = document.querySelectorAll('[aria-live], [role="status"], [role="alert"]');
    return Array.from(liveRegions)
        .map(function readText(element) {
            return element.textContent ?? '';
        })
        .join(' ');
}

afterEach(async () => {
    await dismissEveryToastInApp();
});

describe('the toast region', () => {
    it('UI kit: shows every queued message inside the notifications region, oldest first', async () => {
        await renderSuspended(ToastRegion);

        await showToastInApp({ message: profileSavedMessage });
        await showToastInApp({ message: sessionExpiringMessage });

        const region = readToastRegion();
        const spokenOrder = within(region)
            .getAllByRole('listitem')
            .map(function readText(toast) {
                return toast.textContent ?? '';
            });

        expect(spokenOrder).toHaveLength(2);
        expect(spokenOrder[0]).toContain(profileSavedMessage);
        expect(spokenOrder[1]).toContain(sessionExpiringMessage);
    });

    it('UI kit: announces a new toast through a live region', async () => {
        await renderSuspended(ToastRegion);

        await showToastInApp({ message: sessionExpiringMessage });

        expect(readAnnouncedText()).toContain(sessionExpiringMessage);
    });

    it('UI kit: dismisses the toast whose control was used and leaves the other on screen', async () => {
        await renderSuspended(ToastRegion);
        await showToastInApp({ message: profileSavedMessage });
        await showToastInApp({ message: sessionExpiringMessage });

        const savedToast = readToastSaying(profileSavedMessage);
        await fireEvent.click(within(savedToast).getByRole('button', { name: /dismiss/i }));
        await settleUserInterface();

        const region = readToastRegion();
        expect(within(region).queryByText(profileSavedMessage)).toBeNull();
        expect(within(region).getByText(sessionExpiringMessage)).not.toBeNull();
        expect(await readToastMessages()).toEqual([sessionExpiringMessage]);
    });
});
