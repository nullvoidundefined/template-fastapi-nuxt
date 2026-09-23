<script setup lang="ts">
/**
 * The first signed-in page (spec: B-12, B-50).
 *
 * It names the signed-in address, which is not decoration: it is what proves a server-rendered
 * page shows its own visitor's session rather than whichever one a shared cache happened to hold.
 */
import { definePageMeta, useSeoMeta } from '#imports';

import PasswordChangeForm from '~/components/PasswordChangeForm/PasswordChangeForm.vue';
import { useSessionQuery } from '~/composables/useSessionQuery';

defineOptions({ name: 'DashboardPage' });

definePageMeta({ layout: 'protected', middleware: 'require-session' });

useSeoMeta({
    description: 'Your account.',
    title: 'Dashboard',
});

const { data: signedInUser } = useSessionQuery();
</script>

<template>
    <section data-test-id="dashboard-page">
        <h1>Dashboard</h1>
        <p data-test-id="dashboard-email">Signed in as {{ signedInUser?.email }}</p>
        <PasswordChangeForm />
    </section>
</template>
