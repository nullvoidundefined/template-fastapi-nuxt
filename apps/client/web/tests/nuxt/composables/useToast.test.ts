/**
 * Tests for the toast queue composable (spec: slice 03 PR 4, the design spec's "UI kit" line,
 * US-AUTH-004).
 *
 * A toast store that keeps only the latest message passes a one-toast test and fails here: a
 * password change that succeeds while a session-expiry warning is still on screen would erase the
 * warning. So every test has two toasts queued at once, and the identifier `showToast` returns is
 * what distinguishes them, including when two toasts carry the same words.
 *
 * What the region renders and what a screen reader hears is asserted against the rendered region
 * in tests/nuxt/components/ToastRegion/ToastRegion.test.ts; this file is about the queue alone.
 */
import { describe, it, expect, afterEach } from 'vitest';

import {
    dismissEveryToastInApp,
    dismissToastInApp,
    readToastIds,
    readToastMessages,
    showToastInApp,
} from '../uiKitHarness';

const profileSavedMessage = 'Your profile has been saved.';
const sessionExpiringMessage = 'Your session expires in one minute.';

afterEach(async () => {
    await dismissEveryToastInApp();
});

describe('the toast queue', () => {
    it('UI kit: keeps every queued toast, oldest first', async () => {
        await showToastInApp({ message: profileSavedMessage });
        await showToastInApp({ message: sessionExpiringMessage });

        expect(await readToastMessages()).toEqual([profileSavedMessage, sessionExpiringMessage]);
    });

    it('UI kit: dismisses the toast whose id was given and leaves the rest queued', async () => {
        const profileSavedToastId = await showToastInApp({ message: profileSavedMessage });
        await showToastInApp({ message: sessionExpiringMessage });

        await dismissToastInApp(profileSavedToastId);

        expect(await readToastMessages()).toEqual([sessionExpiringMessage]);
    });

    it('UI kit: identifies two toasts carrying the same message separately', async () => {
        const firstToastId = await showToastInApp({ message: profileSavedMessage });
        const secondToastId = await showToastInApp({ message: profileSavedMessage });

        expect(secondToastId).not.toEqual(firstToastId);
        expect(await readToastIds()).toEqual([firstToastId, secondToastId]);

        await dismissToastInApp(firstToastId);

        expect(await readToastIds()).toEqual([secondToastId]);
        expect(await readToastMessages()).toEqual([profileSavedMessage]);
    });

    it('UI kit: ignores a dismissal for an id that is not queued', async () => {
        await showToastInApp({ message: profileSavedMessage });
        await showToastInApp({ message: sessionExpiringMessage });

        await dismissToastInApp('a-toast-nobody-queued');

        expect(await readToastMessages()).toEqual([profileSavedMessage, sessionExpiringMessage]);
    });
});
