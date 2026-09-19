<script setup lang="ts">
/** Landing page (US-LANDING-001, spec B-49): names the product in the page's only <h1> and links to log in and register. */
import { NuxtLink } from '#components';

import styles from './index.module.scss';

defineOptions({ name: 'LandingPage' });
</script>

<template>
    <section data-test-id="landing-page" :class="styles.landing">
        <h1 :class="styles.title">template-fastapi-nuxt</h1>
        <p :class="styles.lead">A FastAPI and Nuxt starting point for new applications.</p>
        <nav aria-label="Account" :class="styles.actions">
            <NuxtLink to="/login" :class="styles.primaryAction">Log in</NuxtLink>
            <NuxtLink to="/register" :class="styles.secondaryAction">Register</NuxtLink>
        </nav>
    </section>
</template>
