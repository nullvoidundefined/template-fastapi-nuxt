/**
 * Stories for the kit's modal (B-39).
 *
 * The modal reads the stack rather than a prop, so each story opens it through `useModal()` in a
 * wrapper's setup. A story that rendered the component alone would show nothing, and a snapshot of
 * nothing passes forever.
 */
import type { Meta, StoryObj } from '@storybook/vue3-vite';

import { useModal } from '../../../composables/useModal';
import Modal from './Modal.vue';

const meta = {
    title: 'ui/Modal',
    component: Modal,
    args: { id: 'story-modal', title: 'Edit your profile' },
} satisfies Meta<typeof Modal>;

export default meta;

type Story = StoryObj<typeof meta>;

/** Render the modal with the stack already holding it, which is how a page opens one. */
function buildOpenModalStory(preventClose: boolean): Story {
    return {
        render: (args) => ({
            components: { Modal },
            setup() {
                useModal().openModal({ id: args.id, preventClose });
                return { args };
            },
            template: '<Modal v-bind="args">The form goes here.</Modal>',
        }),
    };
}

export const Open: Story = buildOpenModalStory(false);

export const WhileSubmitting: Story = buildOpenModalStory(true);
