<script setup lang="ts">
/**
 * Sets a new password from the emailed link (spec: B-15, B-36). It reads the token from
 * `?token=`, refuses to submit when the two passwords differ, and on success sends the visitor to
 * sign in, because the reset has signed out every session.
 *
 * The token is read once and then removed from the address bar, so it does not linger in the
 * history or in any page URL that analytics records later. A link with no token explains itself
 * rather than showing a form whose submission can only fail.
 */
import { NuxtLink } from '#components';
import { definePageMeta, navigateTo, useRoute, useRouter, useSeoMeta } from '#imports';
import { onMounted, reactive, ref } from 'vue';

import Button from '~/components/ui/Button/Button.vue';
import TextField from '~/components/ui/TextField/TextField.vue';
import { resetPassword } from '~/api/resetPassword';
import { useApiClient } from '~/composables/useApiClient';
import { readFormFailure } from '~/services/forms/readFormFailure';
import { readQueryValue } from '~/services/routing/readQueryValue';
import type { FormFailure } from '~/types/formFailure';
import styles from '~/components/CredentialsForm/CredentialsForm.module.scss';

defineOptions({ name: 'ResetPasswordPage' });

definePageMeta({ layout: 'auth' });

useSeoMeta({ description: 'Choose a new password.', title: 'Reset password' });

const MISMATCH_MESSAGE = 'The two passwords do not match.';

const apiClient = useApiClient();
const route = useRoute();
const router = useRouter();
// Read once at setup: the address bar is cleared on mount, and the submission still needs it.
const linkCredential = readQueryValue(route.query.token);
const hasLinkCredential = linkCredential.length > 0;
const formValues = reactive({ confirmation: '', password: '' });
const isSubmitting = ref(false);
const formFailure = ref<FormFailure>({ fieldMessages: {}, formMessage: undefined });

/** Check the two entries agree, then reset and go to the sign-in page. */
async function submitForm(): Promise<void> {
    const { confirmation, password } = formValues;
    if (password !== confirmation) {
        formFailure.value = { fieldMessages: {}, formMessage: MISMATCH_MESSAGE };
        return;
    }
    isSubmitting.value = true;
    formFailure.value = { fieldMessages: {}, formMessage: undefined };
    try {
        await resetPassword(apiClient, { password, token: String(linkCredential) });
        await addressCleanup;
        await navigateTo('/login?reset=true');
    } catch (failure) {
        formFailure.value = promoteLinkFailure(readFormFailure(failure));
    } finally {
        isSubmitting.value = false;
    }
}

/** Show an error about the link itself for the whole form, since it has no input to sit beside. */
function promoteLinkFailure(readFailure: FormFailure): FormFailure {
    const { fieldMessages } = readFailure;
    const linkMessage = fieldMessages.token;
    return linkMessage ? { fieldMessages, formMessage: linkMessage } : readFailure;
}

// Awaited before leaving the page, so this cleanup cannot land after the navigation to sign-in
// and pull the visitor back here.
let addressCleanup: Promise<unknown> = Promise.resolve();

onMounted(() => {
    if (hasLinkCredential) {
        addressCleanup = router.replace({ path: route.path });
    }
});
</script>

<template>
    <section data-test-id="reset-password-page">
        <h1>Reset password</h1>
        <div v-if="!hasLinkCredential">
            <p role="alert" :class="styles.alert">
                This reset link is incomplete. Links expire after an hour and work once.
            </p>
            <p><NuxtLink to="/forgot-password">Request a new link</NuxtLink></p>
        </div>
        <form v-else :class="styles.form" novalidate @submit.prevent="submitForm">
            <p v-if="formFailure.formMessage" role="alert" :class="styles.alert">
                {{ formFailure.formMessage }}
            </p>
            <TextField
                v-model="formValues.password"
                label="New password"
                name="password"
                type="password"
                autocomplete="new-password"
                :error-message="formFailure.fieldMessages.password"
            />
            <TextField
                v-model="formValues.confirmation"
                label="Confirm new password"
                name="confirmation"
                type="password"
                autocomplete="new-password"
            />
            <Button type="submit" :disabled="isSubmitting">Reset password</Button>
        </form>
    </section>
</template>
