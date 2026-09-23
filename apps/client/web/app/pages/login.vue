<script setup lang="ts">
/**
 * Sign-in page (spec: B-45). Minimal but permanent: slice 03 PR 4 adds the form to it.
 *
 * `redirect-if-session` is what keeps a signed-in visitor off it, and the `auth` layout is what
 * makes it a signed-out page rather than a page with the account controls in the header.
 */
import { NuxtLink } from '#components';
import { definePageMeta, useSeoMeta } from '#imports';

defineOptions({ name: 'LoginPage' });

definePageMeta({ layout: 'auth', middleware: 'redirect-if-session' });

useSeoMeta({
    description: 'Sign in to your account.',
    title: 'Log in',
});
</script>

<template>
    <section data-test-id="login-page">
        <h1>Log in</h1>
        <p>The sign-in form arrives with the ui kit.</p>
        <p>
            No account yet?
            <NuxtLink to="/register">Register</NuxtLink>
        </p>
    </section>
</template>
