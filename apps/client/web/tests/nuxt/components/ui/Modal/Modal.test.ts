/**
 * Tests for the kit's Modal (spec: slice 03 PR 4, the design spec's "UI kit" line, B-48's keyboard
 * requirement, US-AUTH-004).
 *
 * A modal is the component where the accessibility work is either done or only claimed. The three
 * things a keyboard or screen-reader user depends on are asserted here rather than assumed: the
 * dialog announces itself with its title as its accessible name, focus moves into it and cannot
 * wander behind it while it is open, and focus returns to the control that opened it when it
 * closes, so the visitor is not dropped at the top of the document.
 *
 * `preventClose` is tested as the reason it exists. A profile form that is mid-submit must not be
 * dismissable by the escape key or by a stray click on the overlay, because the request is already
 * on its way and the visitor would be left unsure whether it landed. The same modal must still
 * close when the code that opened it decides the work is finished.
 *
 * The dialog is opened through `useModal()` rather than through a prop on the component, because
 * the stack is what the spec makes the source of truth; a modal that renders whenever it is
 * mounted would pass a prop-driven test and ignore the stack entirely.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { h } from 'vue';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { cleanup, screen, fireEvent } from '@testing-library/vue';

import Modal from '~/components/ui/Modal/Modal.vue';

import {
    closeEveryModalInApp,
    closeModalInApp,
    openModalInApp,
    pressPointerOutsideTheDialog,
    readOpenModalIds,
    settleUserInterface,
} from '../../../uiKitHarness';

const profileModalId = 'edit-profile';
const profileModalTitle = 'Edit your profile';
const submitLabel = 'Save changes';
const openerLabel = 'Edit profile';

let opener: HTMLButtonElement | undefined;

/** Put a real control on the page, focused, so focus restoration has somewhere to return to. */
function placeFocusedOpener(): HTMLButtonElement {
    const control = document.createElement('button');
    control.type = 'button';
    control.textContent = openerLabel;
    document.body.appendChild(control);
    control.focus();
    opener = control;
    return control;
}

/** Render the modal with one focusable control inside it, standing in for a form. */
async function renderProfileModal(): Promise<void> {
    await renderSuspended(Modal, {
        props: { id: profileModalId, title: profileModalTitle },
        slots: { default: () => h('button', { type: 'button' }, submitLabel) },
    });
}

/** The dialog as the accessibility tree exposes it, named by the title the modal was given. */
function readProfileDialog(): HTMLElement {
    return screen.getByRole('dialog', { name: profileModalTitle });
}

afterEach(async () => {
    await closeEveryModalInApp();
    opener?.remove();
    opener = undefined;
    // Testing Library's auto-cleanup is off without Vitest globals, so each test's mount would
    // otherwise survive into the next one. Two Modals sharing one id both open, and Reka hides
    // each behind the other, which leaves no accessible dialog for any query to find.
    cleanup();
});

describe('the kit modal', () => {
    it('UI kit: shows nothing until the modal is opened through the stack', async () => {
        await renderProfileModal();

        expect(screen.queryByRole('dialog')).toBeNull();
        expect(screen.queryByRole('button', { name: submitLabel })).toBeNull();
    });

    it('UI kit: announces itself by its title and takes focus when it opens', async () => {
        placeFocusedOpener();
        await renderProfileModal();

        await openModalInApp({ id: profileModalId });

        const dialog = readProfileDialog();
        await vi.waitFor(function checkFocusMoved() {
            expect(dialog.contains(document.activeElement)).toBe(true);
        });
    });

    it('UI kit: pulls focus back inside when something behind the dialog takes it', async () => {
        const control = placeFocusedOpener();
        await renderProfileModal();
        await openModalInApp({ id: profileModalId });
        const dialog = readProfileDialog();

        control.focus();
        await settleUserInterface();

        expect(dialog.contains(document.activeElement)).toBe(true);
        expect(document.activeElement).not.toBe(control);
    });

    it('UI kit: closes on Escape, leaves the stack empty and returns focus to its opener', async () => {
        const control = placeFocusedOpener();
        await renderProfileModal();
        await openModalInApp({ id: profileModalId });
        readProfileDialog();

        await fireEvent.keyDown(document, { key: 'Escape' });
        await settleUserInterface();

        expect(screen.queryByRole('dialog')).toBeNull();
        expect(await readOpenModalIds()).toEqual([]);
        await vi.waitFor(function checkFocusRestored() {
            expect(document.activeElement).toBe(control);
        });
    });

    it('UI kit: closes on a pointer press outside the dialog', async () => {
        placeFocusedOpener();
        await renderProfileModal();
        await openModalInApp({ id: profileModalId });
        readProfileDialog();

        await pressPointerOutsideTheDialog();

        expect(screen.queryByRole('dialog')).toBeNull();
        expect(await readOpenModalIds()).toEqual([]);
    });

    it('UI kit: a preventClose modal survives Escape and an outside press while it submits, and closes when the code closes it', async () => {
        const control = placeFocusedOpener();
        await renderProfileModal();
        await openModalInApp({ id: profileModalId, preventClose: true });
        readProfileDialog();

        await fireEvent.keyDown(document, { key: 'Escape' });
        await settleUserInterface();

        expect(readProfileDialog()).not.toBeNull();
        expect(await readOpenModalIds()).toEqual([profileModalId]);

        await pressPointerOutsideTheDialog();

        expect(readProfileDialog()).not.toBeNull();
        expect(await readOpenModalIds()).toEqual([profileModalId]);

        await closeModalInApp(profileModalId);

        expect(screen.queryByRole('dialog')).toBeNull();
        expect(await readOpenModalIds()).toEqual([]);
        await vi.waitFor(function checkFocusRestored() {
            expect(document.activeElement).toBe(control);
        });
    });
});
