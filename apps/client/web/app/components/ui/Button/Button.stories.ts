/**
 * Stories for the kit's button (B-39).
 *
 * The disabled and secondary stories exist because they are the states a visual regression is
 * most likely to break without anyone noticing: both are rare enough in manual testing to go
 * unlooked at, and both carry their own colours.
 */
import type { Meta, StoryObj } from '@storybook/vue3-vite';

import Button from './Button.vue';

const meta = {
    args: { default: 'Save profile' },
    component: Button,
    title: 'ui/Button',
} satisfies Meta<typeof Button>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Primary: Story = {};

export const Secondary: Story = { args: { variant: 'secondary' } };

export const Disabled: Story = { args: { disabled: true } };
