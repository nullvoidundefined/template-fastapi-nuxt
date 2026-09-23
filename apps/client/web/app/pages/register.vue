<script setup lang="ts">
/**
 * Registration page (spec: B-45). Minimal but permanent: slice 03 PR 4 adds the form to it.
 *
 * It carries the same middleware as the sign-in page rather than a variation of it, because a
 * redirect applied to one signed-out page and forgotten on the other is the likely mistake.
 */
import { NuxtLink } from '#components';
import { definePageMeta, useSeoMeta } from '#imports';

defineOptions({ name: 'RegisterPage' });

definePageMeta({ layout: 'auth', middleware: 'redirect-if-session' });

useSeoMeta({
    title: 'Register',
    description: 'Create an account.',
});
</script>

<template>
    <section data-test-id="register-page">
        <h1>Register</h1>
        <p>The registration form arrives with the ui kit.</p>
        <p>
            Already have an account?
            <NuxtLink to="/login">Log in</NuxtLink>
        </p>
    </section>
</template>
