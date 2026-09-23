<script setup lang="ts">
/**
 * Layout for the signed-out pages, log in and register.
 *
 * It is deliberately narrower than the default layout and carries no account controls: the one
 * thing someone on these pages can do is the form in front of them.
 *
 * It has no <h1>, because each page owns its one heading.
 */
import { NuxtLink } from '#components';

import styles from './auth.module.scss';

defineOptions({ name: 'AuthLayout' });
</script>

<template>
    <div data-test-id="auth-layout" :class="styles.shell">
        <header :class="styles.header">
            <NuxtLink to="/" :class="styles.brand">template-fastapi-nuxt</NuxtLink>
        </header>
        <main :class="styles.main">
            <slot />
        </main>
    </div>
</template>
