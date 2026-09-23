/**
 * The shared rig for the ui kit tests (spec: slice 03 PR 4, the "UI kit" line of the design spec,
 * B-39 and B-48).
 *
 * Two things about the kit's state shape everything here.
 *
 * First, the modal stack and the toast queue live in `useState` composables, and `useState` needs
 * the Nuxt app context. A test has no component instance, so every call into `useModal()` or
 * `useToast()` goes through `nuxtApp.runWithContext`, exactly as the session-gate harness runs a
 * route middleware. Each wrapper below calls the composable freshly inside that context and then
 * invokes one function on it, so the tests pass whether the composable captures its state once at
 * setup or resolves it again on every call.
 *
 * Second, one Nuxt app instance serves a whole test file, so the stack and the queue outlive each
 * test. `closeEveryModalInApp` and `dismissEveryToastInApp` are the reset the `afterEach` hooks
 * call, and nothing here seeds state a later test could mistake for its own.
 *
 * `pressPointerOutsideTheDialog` deserves its own note. Reka's dismissable layer listens on the
 * document for a pointer press whose target sits outside the dialog content and dismisses the
 * topmost layer when it finds one; the overlay is such a target, and so is the page behind it.
 * The press is therefore dispatched on the document body, which is the same event path a click on
 * the overlay takes, and it carries `pointerType: 'mouse'` because the layer defers a touch press
 * to the following click.
 */
import { nextTick } from 'vue';
import { useNuxtApp } from '#app';
import { fireEvent } from '@testing-library/vue';

import { useModal } from '~/composables/useModal';
import { useToast } from '~/composables/useToast';

/** The part of a stack entry these tests read: the id the modal was opened under. */
type ModalEntry = { id: string };

/** The part of a queued toast these tests read: its identifier and the words it says. */
type ToastEntry = { id: string; message: string };

/** How long the kit's own transitions and Reka's focus work need before the DOM is worth reading. */
const settleDelayInMilliseconds = 20;

/** Let Vue flush, then let the primitives' own queued work run, before the DOM is asserted on. */
export async function settleUserInterface(): Promise<void> {
    await nextTick();
    await new Promise(function waitForQueuedWork(resolve) {
        setTimeout(resolve, settleDelayInMilliseconds);
    });
}

/** Open a modal through the composable, the way a page's handler would. */
export async function openModalInApp(options: {
    id: string;
    preventClose?: boolean;
}): Promise<void> {
    await useNuxtApp().runWithContext(function openOne(): void {
        useModal().openModal(options);
    });
    await settleUserInterface();
}

/** Close one modal by id, the explicit close a `preventClose` modal still honours. */
export async function closeModalInApp(id: string): Promise<void> {
    await useNuxtApp().runWithContext(function closeOne(): void {
        useModal().closeModal(id);
    });
    await settleUserInterface();
}

/** Empty the whole stack, as a sign-out or a route change would. */
export async function closeEveryModalInApp(): Promise<void> {
    await useNuxtApp().runWithContext(function closeAll(): void {
        useModal().closeAllModals();
    });
    await settleUserInterface();
}

/** The ids currently on the stack, oldest first, so ordering is assertable. */
export async function readOpenModalIds(): Promise<string[]> {
    return await useNuxtApp().runWithContext(function readIds(): string[] {
        return useModal().openModals.value.map(function readId(entry: ModalEntry) {
            return entry.id;
        });
    });
}

/** Whether one modal is open, asked the way a component asks. */
export async function readModalIsOpen(id: string): Promise<boolean> {
    return await useNuxtApp().runWithContext(function readOne(): boolean {
        return useModal().isModalOpen(id);
    });
}

/** Queue a toast and hand back the identifier that dismisses that one toast. */
export async function showToastInApp(options: { message: string }): Promise<string> {
    const toastId = await useNuxtApp().runWithContext(function showOne(): string {
        return useToast().showToast(options);
    });
    await settleUserInterface();
    return toastId;
}

/** Dismiss one toast by its identifier. */
export async function dismissToastInApp(toastId: string): Promise<void> {
    await useNuxtApp().runWithContext(function dismissOne(): void {
        useToast().dismissToast(toastId);
    });
    await settleUserInterface();
}

/** The queued toast messages, oldest first. */
export async function readToastMessages(): Promise<string[]> {
    return await useNuxtApp().runWithContext(function readMessages(): string[] {
        return useToast().toasts.value.map(function readMessage(entry: ToastEntry) {
            return entry.message;
        });
    });
}

/** The queued toast identifiers, oldest first. */
export async function readToastIds(): Promise<string[]> {
    return await useNuxtApp().runWithContext(function readIds(): string[] {
        return useToast().toasts.value.map(function readId(entry: ToastEntry) {
            return entry.id;
        });
    });
}

/** Empty the queue between tests, so one test's toasts cannot answer the next one's assertions. */
export async function dismissEveryToastInApp(): Promise<void> {
    const toastIds = await readToastIds();
    for (const toastId of toastIds) {
        await dismissToastInApp(toastId);
    }
}

/** Press the pointer on the page behind the dialog, the interaction an overlay click performs. */
export async function pressPointerOutsideTheDialog(): Promise<void> {
    await fireEvent.pointerDown(document.body, { pointerType: 'mouse' });
    await fireEvent.click(document.body);
    await settleUserInterface();
}
