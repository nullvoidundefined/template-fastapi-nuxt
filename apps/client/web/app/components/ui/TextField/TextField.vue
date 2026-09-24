<script setup lang="ts">
/**
 * The kit's labelled text input (spec: B-38, B-48).
 *
 * The error is tied to the input with `aria-describedby` and `aria-invalid`, so a screen reader
 * announces it with the field rather than leaving it as nearby text. The ids come from `useId`, so
 * server and client render the same ones.
 */
import { computed, useId } from 'vue';

import styles from './TextField.module.scss';

defineOptions({ name: 'UiTextField' });

const props = withDefaults(
    defineProps<{
        autocomplete?: string;
        errorMessage?: string;
        label: string;
        modelValue: string;
        name: string;
        type?: 'email' | 'password' | 'text';
    }>(),
    { autocomplete: undefined, errorMessage: undefined, type: 'text' },
);

defineEmits<{
    'update:modelValue': [value: string];
}>();

const inputId = useId();
const errorId = `${inputId}-error`;
const hasError = computed(() => Boolean(props.errorMessage));
</script>

<template>
    <div :class="styles.field">
        <label :for="inputId" :class="styles.label">
            <span>{{ label }}</span>
            <input
                :id="inputId"
                :class="[styles.input, hasError ? styles.invalid : undefined]"
                :type="type"
                :name="name"
                :autocomplete="autocomplete"
                :value="modelValue"
                :aria-invalid="hasError ? 'true' : undefined"
                :aria-describedby="hasError ? errorId : undefined"
                @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
            />
        </label>
        <p v-if="hasError" :id="errorId" :class="styles.error">{{ errorMessage }}</p>
    </div>
</template>
