/**
 * The modal stack (spec: the design spec's "UI kit" line).
 *
 * A stack rather than one current modal, because modals genuinely nest: a confirmation opened from
 * a form has to close back to the form rather than to the page behind it. A store holding a single
 * modal satisfies every one-modal test and loses the form.
 *
 * `preventClose` exists for a form that is mid-submit. The request is already on its way, so the
 * escape key and a stray press on the overlay must not dismiss it and leave the visitor unsure
 * whether it landed; the code that opened it still closes it when the work finishes.
 */
import { useState } from '#app';
import type { Ref } from 'vue';

export type ModalEntry = {
    id: string;
    preventClose: boolean;
};

type ModalStack = {
    openModals: Ref<ModalEntry[]>;
    openModal: (options: { id: string; preventClose?: boolean }) => void;
    closeModal: (id: string) => void;
    closeAllModals: () => void;
    isModalOpen: (id: string) => boolean;
    isModalDismissable: (id: string) => boolean;
};

const MODAL_STACK_STATE_KEY = 'ui-modal-stack';

/** Return the stack and the named functions that change it; nothing writes the state directly. */
export function useModal(): ModalStack {
    const openModals = useState<ModalEntry[]>(MODAL_STACK_STATE_KEY, () => []);

    function openModal({ id, preventClose = false }: { id: string; preventClose?: boolean }): void {
        if (openModals.value.some((entry) => entry.id === id)) {
            return;
        }
        openModals.value = [...openModals.value, { id, preventClose }];
    }

    function closeModal(id: string): void {
        openModals.value = openModals.value.filter((entry) => entry.id !== id);
    }

    function closeAllModals(): void {
        openModals.value = [];
    }

    function isModalOpen(id: string): boolean {
        return openModals.value.some((entry) => entry.id === id);
    }

    /** Whether the visitor may dismiss this modal themselves, as opposed to the code closing it. */
    function isModalDismissable(id: string): boolean {
        const entry = openModals.value.find((openEntry) => openEntry.id === id);
        return entry !== undefined && !entry.preventClose;
    }

    return { closeAllModals, closeModal, isModalDismissable, isModalOpen, openModal, openModals };
}
