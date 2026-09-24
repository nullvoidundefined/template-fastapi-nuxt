<script setup lang="ts">
/**
 * Sign-in page (spec: B-11, B-45).
 *
 * `redirect-if-session` is what keeps a signed-in visitor off it, and the `auth` layout is what
 * makes it a signed-out page rather than a page with the account controls in the header.
 */
import { NuxtLink } from '#components';
import { definePageMeta, navigateTo, useRoute, useSeoMeta } from '#imports';
import { computed } from 'vue';

import CredentialsForm from '~/components/CredentialsForm/CredentialsForm.vue';
import { useSignInMutation } from '~/composables/useSignInMutation';
import type { CredentialsInput } from '~/types/credentialsInput';

defineOptions({ name: 'LoginPage' });

definePageMeta({ layout: 'auth', middleware: 'redirect-if-session' });

useSeoMeta({
    description: 'Sign in to your account.',
    title: 'Log in',
});

const signInMutation = useSignInMutation();
const route = useRoute();
// Set by the reset page on success (B-36), so the visitor knows the new password is in effect.
const hasJustReset = computed(() => route.query.reset === 'true');

/** Sign in, then go to the dashboard. */
async function signInAndContinue(credentials: CredentialsInput): Promise<void> {
    await signInMutation.mutateAsync(credentials);
    await navigateTo('/dashboard');
}
</script>

<template>
    <section data-test-id="login-page">
        <h1>Log in</h1>
        <p v-if="hasJustReset" role="status">
            Your password has been reset. Log in with the new one.
        </p>
        <CredentialsForm
            submit-label="Log in"
            password-autocomplete="current-password"
            :submit-credentials="signInAndContinue"
        />
        <p><NuxtLink to="/forgot-password">Forgot your password?</NuxtLink></p>
        <p>
            No account yet?
            <NuxtLink to="/register">Register</NuxtLink>
        </p>
    </section>
</template>
