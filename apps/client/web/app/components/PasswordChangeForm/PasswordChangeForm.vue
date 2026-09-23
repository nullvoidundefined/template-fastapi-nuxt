<script setup lang="ts">
/**
 * The dashboard's profile form: change the password (spec: B-13, B-50).
 *
 * Success is announced in a `status` region and a refusal in an `alert`, so both reach a screen
 * reader without moving focus.
 */
import { reactive, ref } from 'vue';

import Button from '~/components/ui/Button/Button.vue';
import TextField from '~/components/ui/TextField/TextField.vue';
import { useChangePasswordMutation } from '~/composables/useChangePasswordMutation';
import { readFormFailure, type FormFailure } from '~/services/forms/readFormFailure';
import styles from '../CredentialsForm/CredentialsForm.module.scss';

defineOptions({ name: 'PasswordChangeForm' });

const PASSWORD_CHANGED_MESSAGE = 'Password changed. Your other sessions have been signed out.';

const changePasswordMutation = useChangePasswordMutation();
const formValues = reactive({ current_password: '', new_password: '' });
const formFailure = ref<FormFailure>({ fieldMessages: {}, formMessage: undefined });
const successMessage = ref('');

/** Submit the change and show the result. */
async function submitForm(): Promise<void> {
    formFailure.value = { fieldMessages: {}, formMessage: undefined };
    successMessage.value = '';
    try {
        await changePasswordMutation.mutateAsync({ ...formValues });
        successMessage.value = PASSWORD_CHANGED_MESSAGE;
        formValues.current_password = '';
        formValues.new_password = '';
    } catch (failure) {
        formFailure.value = readFormFailure(failure);
    }
}
</script>

<template>
    <form :class="styles.form" novalidate @submit.prevent="submitForm">
        <h2>Change password</h2>
        <p v-if="formFailure.formMessage" role="alert" :class="styles.alert">
            {{ formFailure.formMessage }}
        </p>
        <p role="status">{{ successMessage }}</p>
        <TextField
            v-model="formValues.current_password"
            label="Current password"
            name="current_password"
            type="password"
            autocomplete="current-password"
            :error-message="formFailure.fieldMessages.current_password"
        />
        <TextField
            v-model="formValues.new_password"
            label="New password"
            name="new_password"
            type="password"
            autocomplete="new-password"
            :error-message="formFailure.fieldMessages.new_password"
        />
        <Button type="submit" :disabled="changePasswordMutation.isPending.value">
            Change password
        </Button>
    </form>
</template>
