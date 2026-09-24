/**
 * Tests for the modal stack composable (spec: slice 03 PR 4, the design spec's "UI kit" line,
 * US-AUTH-004).
 *
 * The spec says stack, not current modal, and that word is the whole point of this file. A store
 * that holds one current modal passes every single-modal test and fails here: opening a second
 * modal over the first would throw the first away, so closing the second would leave the visitor
 * looking at the page instead of at the confirmation dialog they were already in. Each test below
 * therefore has two modals open at once, or asserts what survives a close.
 *
 * `preventClose` is checked here only in its store half, the half that says an explicit close
 * still works. The half that matters to a visitor, that escape and a click outside do nothing
 * while a form is submitting, is asserted against the rendered dialog in
 * tests/nuxt/components/ui/Modal/Modal.test.ts.
 */
import { describe, it, expect, afterEach } from 'vitest';

import {
    closeEveryModalInApp,
    closeModalInApp,
    openModalInApp,
    readModalIsOpen,
    readOpenModalIds,
} from '../uiKitHarness';

const confirmDeleteModalId = 'confirm-delete-account';
const sessionExpiringModalId = 'session-expiring';

afterEach(async () => {
    await closeEveryModalInApp();
});

describe('the modal stack', () => {
    it('UI kit: keeps the first modal open when a second one opens over it and then closes', async () => {
        await openModalInApp({ id: confirmDeleteModalId });
        await openModalInApp({ id: sessionExpiringModalId });

        expect(await readOpenModalIds()).toEqual([confirmDeleteModalId, sessionExpiringModalId]);

        await closeModalInApp(sessionExpiringModalId);

        expect(await readModalIsOpen(sessionExpiringModalId)).toBe(false);
        expect(await readModalIsOpen(confirmDeleteModalId)).toBe(true);
        expect(await readOpenModalIds()).toEqual([confirmDeleteModalId]);
    });

    it('UI kit: closes a modal underneath without disturbing the one above it', async () => {
        await openModalInApp({ id: confirmDeleteModalId });
        await openModalInApp({ id: sessionExpiringModalId });

        await closeModalInApp(confirmDeleteModalId);

        expect(await readOpenModalIds()).toEqual([sessionExpiringModalId]);
        expect(await readModalIsOpen(sessionExpiringModalId)).toBe(true);
    });

    it('UI kit: closeAllModals empties a stack of several modals', async () => {
        await openModalInApp({ id: confirmDeleteModalId });
        await openModalInApp({ id: sessionExpiringModalId });

        await closeEveryModalInApp();

        expect(await readOpenModalIds()).toEqual([]);
        expect(await readModalIsOpen(confirmDeleteModalId)).toBe(false);
        expect(await readModalIsOpen(sessionExpiringModalId)).toBe(false);
    });

    it('UI kit: closes a modal opened with preventClose when the code asks explicitly', async () => {
        await openModalInApp({ id: confirmDeleteModalId, preventClose: true });

        await closeModalInApp(confirmDeleteModalId);

        expect(await readModalIsOpen(confirmDeleteModalId)).toBe(false);
        expect(await readOpenModalIds()).toEqual([]);
    });

    it('UI kit: ignores a close for an id that is not open, leaving the stack as it was', async () => {
        await openModalInApp({ id: confirmDeleteModalId });
        await openModalInApp({ id: sessionExpiringModalId });

        await closeModalInApp('a-modal-nobody-opened');

        expect(await readOpenModalIds()).toEqual([confirmDeleteModalId, sessionExpiringModalId]);
    });
});
