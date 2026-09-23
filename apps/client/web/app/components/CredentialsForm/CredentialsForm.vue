<script setup lang="ts">
/**
 * The email-and-password form both signed-out pages use (spec: B-10, B-11, B-38).
 *
 * The page passes the submission, so register and login share every behavior (field errors, the
 * form-level alert, the pending state) and differ only in the call and the labels.
 */
import { reactive, ref } from 'vue';

import Button from '~/components/ui/Button/Button.vue';
import TextField from '~/components/ui/TextField/TextField.vue';
import { readFormFailure, type FormFailure } from '~/services/forms/readFormFailure';
import type { CredentialsInput } from '~/types/credentialsInput';
import styles from './CredentialsForm.module.scss';

defineOptions({ name: 'CredentialsForm' });

const props = defineProps<{
    passwordAutocomplete: 'current-password' | 'new-password';
    submitCredentials: (credentials: CredentialsInput) => Promise<unknown>;
    submitLabel: string;
}>();

const formValues = reactive({ email: '', password: '' });
const formFailure = ref<FormFailure>({ fieldMessages: {}, formMessage: undefined });
const isSubmitting = ref(false);

/** Submit the typed credentials and show whatever the backend refused. */
async function submitForm(): Promise<void> {
    isSubmitting.value = true;
    formFailure.value = { fieldMessages: {}, formMessage: undefined };
    try {
        await props.submitCredentials({ ...formValues });
    } catch (failure) {
        formFailure.value = readFormFailure(failure);
    } finally {
        isSubmitting.value = false;
    }
}
</script>

<template>
    <form :class="styles.form" novalidate @submit.prevent="submitForm">
        <p v-if="formFailure.formMessage" role="alert" :class="styles.alert">
            {{ formFailure.formMessage }}
        </p>
        <TextField
            v-model="formValues.email"
            label="Email"
            name="email"
            type="email"
            autocomplete="email"
            :error-message="formFailure.fieldMessages.email"
        />
        <TextField
            v-model="formValues.password"
            label="Password"
            name="password"
            type="password"
            :autocomplete="passwordAutocomplete"
            :error-message="formFailure.fieldMessages.password"
        />
        <Button type="submit" :disabled="isSubmitting">{{ submitLabel }}</Button>
    </form>
</template>
