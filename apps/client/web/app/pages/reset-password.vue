<script setup lang="ts">
/**
 * Sets a new password from the emailed link (spec: B-15, B-36). It reads the token from
 * `?token=`, refuses to submit when the two passwords differ, and on success sends the visitor to
 * sign in, because the reset has signed out every session.
 */
import { definePageMeta, navigateTo, useRoute, useSeoMeta } from '#imports';
import { computed, reactive, ref } from 'vue';

import Button from '~/components/ui/Button/Button.vue';
import TextField from '~/components/ui/TextField/TextField.vue';
import { resetPassword } from '~/api/resetPassword';
import { useApiClient } from '~/composables/useApiClient';
import { readFormFailure } from '~/services/forms/readFormFailure';
import type { FormFailure } from '~/types/formFailure';
import styles from '~/components/CredentialsForm/CredentialsForm.module.scss';

defineOptions({ name: 'ResetPasswordPage' });

definePageMeta({ layout: 'auth' });

useSeoMeta({ description: 'Choose a new password.', title: 'Reset password' });

const MISMATCH_MESSAGE = 'The two passwords do not match.';

const apiClient = useApiClient();
const route = useRoute();
const resetToken = computed(() => String(route.query.token ?? ''));
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
        await resetPassword(apiClient, { password, token: resetToken.value });
        await navigateTo('/login?reset=true');
    } catch (failure) {
        formFailure.value = readFormFailure(failure);
    } finally {
        isSubmitting.value = false;
    }
}
</script>

<template>
    <section data-test-id="reset-password-page">
        <h1>Reset password</h1>
        <form :class="styles.form" novalidate @submit.prevent="submitForm">
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
