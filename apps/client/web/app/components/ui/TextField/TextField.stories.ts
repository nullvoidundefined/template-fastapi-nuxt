/**
 * Stories for the kit's text field (B-39). The error story is the state B-38 depends on.
 */
import type { Meta, StoryObj } from '@storybook/vue3-vite';

import TextField from './TextField.vue';

const meta = {
    args: { label: 'Email', modelValue: '', name: 'email', type: 'email' },
    component: TextField,
    title: 'ui/TextField',
} satisfies Meta<typeof TextField>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Empty: Story = {};

export const Filled: Story = { args: { modelValue: 'reader@example.test' } };

export const WithError: Story = {
    args: { errorMessage: 'Enter a valid email address', modelValue: 'no-at-sign' },
};
