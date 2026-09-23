<script setup lang="ts">
/**
 * One notification in the toast region (spec: the design spec's "UI kit" line).
 *
 * It is a list item carrying its message and the control that dismisses it, because the region is
 * a list of notifications and a screen reader should be able to count them and move through them.
 * The dismissal names the message in its accessible name rather than saying only "Dismiss", so a
 * visitor with several toasts open knows which one they are closing.
 */
import styles from './Toast.module.scss';

defineOptions({ name: 'UiToast' });

defineProps<{
    message: string;
}>();

defineEmits<{
    dismiss: [];
}>();
</script>

<template>
    <li :class="styles.toast">
        <p :class="styles.message">{{ message }}</p>
        <button
            type="button"
            :class="styles.dismiss"
            :aria-label="`Dismiss: ${message}`"
            @click="$emit('dismiss')"
        >
            Dismiss
        </button>
    </li>
</template>
