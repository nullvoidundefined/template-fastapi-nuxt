<script setup lang="ts">
/**
 * The kit's modal (spec: the design spec's "UI kit" line, B-48).
 *
 * Reka's dialog primitives carry the parts that are wrong more often than they are right when
 * hand-written: the dialog role and its accessible name, the focus move into the dialog, the focus
 * trap while it is open, and the return of focus to whatever opened it. None of that is
 * reimplemented here.
 *
 * Whether the modal is open is read from the stack rather than from a prop, because the stack is
 * the source of truth the spec names; a modal that rendered whenever it was mounted would ignore
 * the stack entirely. A `preventClose` modal refuses the two dismissals the visitor can perform,
 * the escape key and a press outside, and still closes when the code asks.
 */
import {
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogOverlay,
    DialogPortal,
    DialogRoot,
    DialogTitle,
} from 'reka-ui';
import { computed } from 'vue';

import { useModal } from '~/composables/useModal';
import styles from './Modal.module.scss';

defineOptions({ name: 'UiModal' });

const props = withDefaults(
    defineProps<{
        id: string;
        title: string;
        description?: string;
        closeLabel?: string;
    }>(),
    { description: undefined, closeLabel: 'Close' },
);

const { closeModal, isModalDismissable, isModalOpen } = useModal();

const isOpen = computed(() => isModalOpen(props.id));

/** Refuse a dismissal the visitor performed while the modal is holding work open. */
function keepOpenWhileWorking(dismissEvent: Event): void {
    if (!isModalDismissable(props.id)) {
        dismissEvent.preventDefault();
    }
}

/** Reka reports the open state it wants; only a close is ours to apply. */
function applyOpenState(nextOpen: boolean): void {
    if (!nextOpen) {
        closeModal(props.id);
    }
}
</script>

<template>
    <DialogRoot :open="isOpen" @update:open="applyOpenState">
        <DialogPortal>
            <DialogOverlay :class="styles.overlay" />
            <DialogContent
                :class="styles.content"
                @escape-key-down="keepOpenWhileWorking"
                @pointer-down-outside="keepOpenWhileWorking"
                @interact-outside="keepOpenWhileWorking"
            >
                <DialogTitle :class="styles.title">{{ title }}</DialogTitle>
                <DialogDescription v-if="description" :class="styles.description">
                    {{ description }}
                </DialogDescription>
                <div :class="styles.body">
                    <slot />
                </div>
                <DialogClose v-if="isModalDismissable(id)" :class="styles.close">
                    {{ closeLabel }}
                </DialogClose>
            </DialogContent>
        </DialogPortal>
    </DialogRoot>
</template>
