/**
 * The toast queue (spec: the design spec's "UI kit" line).
 *
 * A queue rather than one current message, because a second notification must not silently replace
 * the first one a visitor has not read yet. Each toast carries an identifier of its own so two
 * toasts saying the same words stay separately dismissable, which a message-keyed store cannot do.
 */
import { useState } from '#app';
import type { Ref } from 'vue';

export type ToastEntry = {
    id: string;
    message: string;
};

type ToastQueue = {
    toasts: Ref<ToastEntry[]>;
    showToast: (options: { message: string }) => string;
    dismissToast: (id: string) => void;
};

const TOAST_QUEUE_STATE_KEY = 'ui-toast-queue';

/** Return the queue and the named functions that change it; nothing writes the state directly. */
export function useToast(): ToastQueue {
    const toasts = useState<ToastEntry[]>(TOAST_QUEUE_STATE_KEY, () => []);

    /** Queue one toast and return the identifier that dismisses that one. */
    function showToast({ message }: { message: string }): string {
        const id = crypto.randomUUID();
        toasts.value = [...toasts.value, { id, message }];
        return id;
    }

    function dismissToast(id: string): void {
        toasts.value = toasts.value.filter((entry) => entry.id !== id);
    }

    return { dismissToast, showToast, toasts };
}
