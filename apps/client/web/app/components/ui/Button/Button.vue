<script setup lang="ts">
/**
 * The kit's button (spec: the design spec's "UI kit" line).
 *
 * It renders Reka's `Primitive` as a real `<button>` rather than a styled `<div>` with a role, so
 * the keyboard behaviour, the disabled semantics and the form participation come from the platform
 * instead of being reimplemented and half-remembered.
 *
 * The type defaults to `button`. A button inside a form submits it by default, which turns a
 * cancel control into a submit the first time someone puts one in a form.
 */
import { Primitive } from 'reka-ui';

import styles from './Button.module.scss';

defineOptions({ name: 'UiButton' });

withDefaults(
    defineProps<{
        type?: 'button' | 'submit';
        disabled?: boolean;
        variant?: 'primary' | 'secondary';
    }>(),
    { type: 'button', disabled: false, variant: 'primary' },
);
</script>

<template>
    <Primitive
        as="button"
        :type="type"
        :disabled="disabled"
        :class="[styles.button, variant === 'secondary' ? styles.secondary : styles.primary]"
    >
        <slot />
    </Primitive>
</template>
