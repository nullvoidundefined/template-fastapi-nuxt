<script setup lang="ts">
/**
 * The one place toasts appear (spec: the design spec's "UI kit" line).
 *
 * It is a landmark region named "Notifications" holding a list, and the list is a polite live
 * region, so a message that arrives while the visitor is reading something else is announced
 * without interrupting them. Politeness rather than assertiveness is deliberate: a toast is by
 * definition not the thing the visitor is doing.
 *
 * The region renders in the layout rather than beside whatever raised the toast, so a toast
 * survives the component that queued it.
 */
import Toast from '~/components/ui/Toast/Toast.vue';
import { useToast } from '~/composables/useToast';
import styles from './ToastRegion.module.scss';

defineOptions({ name: 'ToastRegion' });

const { toasts, dismissToast } = useToast();
</script>

<template>
    <section aria-label="Notifications" :class="styles.region">
        <ul aria-live="polite" :class="styles.list">
            <Toast
                v-for="toast in toasts"
                :key="toast.id"
                :message="toast.message"
                @dismiss="dismissToast(toast.id)"
            />
        </ul>
    </section>
</template>
