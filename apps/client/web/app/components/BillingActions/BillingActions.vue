<script setup lang="ts">
/**
 * The dashboard's billing buttons (spec: B-50's billing half, B-22, B-33).
 *
 * Subscribe starts Checkout for the configured price and Manage billing opens Stripe's portal;
 * both leave the app for the URL the backend returns. A refusal, such as no billing account yet,
 * is shown here and the visitor stays on the dashboard.
 */
import { useRuntimeConfig } from '#imports';
import { ref } from 'vue';

import { createCheckoutSession } from '~/api/createCheckoutSession';
import { createPortalSession } from '~/api/createPortalSession';
import Button from '~/components/ui/Button/Button.vue';
import { useApiClient } from '~/composables/useApiClient';
import { readFormFailure } from '~/services/forms/readFormFailure';
import { openExternalUrl } from '~/services/navigation/openExternalUrl';
import styles from './BillingActions.module.scss';

defineOptions({ name: 'BillingActions' });

const apiClient = useApiClient();
const { stripePriceId } = useRuntimeConfig().public;
const failureMessage = ref<string | undefined>(undefined);
const isLeaving = ref(false);

/** Ask the backend for a Stripe URL and leave for it, or show why it refused. */
async function leaveForStripe(requestStripeUrl: () => Promise<string>): Promise<void> {
    failureMessage.value = undefined;
    isLeaving.value = true;
    try {
        openExternalUrl(await requestStripeUrl());
    } catch (failure) {
        failureMessage.value = readFormFailure(failure).formMessage;
        isLeaving.value = false;
    }
}

/** Start Checkout for the configured price. */
async function startSubscription(): Promise<void> {
    await leaveForStripe(() => createCheckoutSession(apiClient, String(stripePriceId)));
}

/** Open the billing portal. */
async function openBillingPortal(): Promise<void> {
    await leaveForStripe(() => createPortalSession(apiClient));
}
</script>

<template>
    <section :class="styles.billing" data-test-id="billing-actions">
        <h2>Billing</h2>
        <p v-if="failureMessage" role="alert" :class="styles.alert">{{ failureMessage }}</p>
        <div :class="styles.buttons">
            <Button :disabled="isLeaving" @click="startSubscription">Subscribe</Button>
            <Button variant="secondary" :disabled="isLeaving" @click="openBillingPortal">
                Manage billing
            </Button>
        </div>
    </section>
</template>
