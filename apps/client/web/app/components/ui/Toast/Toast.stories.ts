/**
 * Stories for one notification (B-39).
 *
 * The long message is not padding: a toast whose text wraps is where the layout of the dismiss
 * control breaks, and it is the case a short sample never shows.
 */
import type { Meta, StoryObj } from '@storybook/vue3-vite';

import Toast from './Toast.vue';

const meta = {
    title: 'ui/Toast',
    component: Toast,
    args: { message: 'Your profile has been saved.' },
} satisfies Meta<typeof Toast>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const LongMessage: Story = {
    args: {
        message:
            'Your session expires in one minute. Save anything you are working on before it does.',
    },
};
