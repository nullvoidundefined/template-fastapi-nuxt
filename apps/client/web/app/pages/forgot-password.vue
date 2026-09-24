<script setup lang="ts">
/**
 * Asks for a reset email (spec: B-14, B-36). After sending, the form is replaced by a submitted
 * state that reads the same whether or not the address has an account.
 */
import { NuxtLink } from '#components';
import { definePageMeta, useSeoMeta } from '#imports';
import { ref } from 'vue';

import Button from '~/components/ui/Button/Button.vue';
import TextField from '~/components/ui/TextField/TextField.vue';
import { requestPasswordReset } from '~/api/requestPasswordReset';
import { useApiClient } from '~/composables/useApiClient';
import { readFormFailure } from '~/services/forms/readFormFailure';
import type { FormFailure } from '~/types/formFailure';
import styles from '~/components/CredentialsForm/CredentialsForm.module.scss';

defineOptions({ name: 'ForgotPasswordPage' });

definePageMeta({ layout: 'auth' });

useSeoMeta({ description: 'Get a link to reset your password.', title: 'Forgot password' });

const apiClient = useApiClient();
const email = ref('');
const hasSubmitted = ref(false);
const isSubmitting = ref(false);
const formFailure = ref<FormFailure>({ fieldMessages: {}, formMessage: undefined });

/** Send the request and switch to the submitted state. */
async function submitForm(): Promise<void> {
    isSubmitting.value = true;
    formFailure.value = { fieldMessages: {}, formMessage: undefined };
    try {
        await requestPasswordReset(apiClient, email.value);
        hasSubmitted.value = true;
    } catch (failure) {
        formFailure.value = readFormFailure(failure);
    } finally {
        isSubmitting.value = false;
    }
}
</script>

<template>
    <section data-test-id="forgot-password-page">
        <h1>Forgot password</h1>
        <p v-if="hasSubmitted" role="status">
            Check your email. If an account uses that address, a reset link is on its way.
        </p>
        <form v-else :class="styles.form" novalidate @submit.prevent="submitForm">
            <p v-if="formFailure.formMessage" role="alert" :class="styles.alert">
                {{ formFailure.formMessage }}
            </p>
            <TextField
                v-model="email"
                label="Email"
                name="email"
                type="email"
                autocomplete="email"
                :error-message="formFailure.fieldMessages.email"
            />
            <Button type="submit" :disabled="isSubmitting">Send reset link</Button>
        </form>
        <p><NuxtLink to="/login">Back to log in</NuxtLink></p>
    </section>
</template>
