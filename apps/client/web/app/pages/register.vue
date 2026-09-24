<script setup lang="ts">
/**
 * Registration page (spec: B-10, B-38, B-45).
 *
 * It carries the same middleware as the sign-in page rather than a variation of it, because a
 * redirect applied to one signed-out page and forgotten on the other is the likely mistake.
 */
import { NuxtLink } from '#components';
import { definePageMeta, navigateTo, useSeoMeta } from '#imports';

import CredentialsForm from '~/components/CredentialsForm/CredentialsForm.vue';
import { useRegisterMutation } from '~/composables/useRegisterMutation';
import type { CredentialsInput } from '~/types/credentialsInput';

defineOptions({ name: 'RegisterPage' });

definePageMeta({ layout: 'auth', middleware: 'redirect-if-session' });

useSeoMeta({
    description: 'Create an account.',
    title: 'Register',
});

const registerMutation = useRegisterMutation();

/** Register, then go to the dashboard. */
async function registerAndContinue(credentials: CredentialsInput): Promise<void> {
    await registerMutation.mutateAsync(credentials);
    await navigateTo('/dashboard');
}
</script>

<template>
    <section data-test-id="register-page">
        <h1>Register</h1>
        <CredentialsForm
            submit-label="Create account"
            password-autocomplete="new-password"
            :submit-credentials="registerAndContinue"
        />
        <p>
            Already have an account?
            <NuxtLink to="/login">Log in</NuxtLink>
        </p>
    </section>
</template>
