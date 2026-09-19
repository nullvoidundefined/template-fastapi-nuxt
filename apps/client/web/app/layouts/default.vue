<script setup lang="ts">
/**
 * Default layout: the site header and the main landmark every page renders into.
 * It has no <h1>, because each page owns its one heading.
 */
import { NuxtLink } from '#components';

import styles from './default.module.scss';

defineOptions({ name: 'DefaultLayout' });
</script>

<template>
    <div data-test-id="default-layout" :class="styles.shell">
        <header :class="styles.header">
            <NuxtLink to="/" :class="styles.brand">template-fastapi-nuxt</NuxtLink>
        </header>
        <main :class="styles.main">
            <slot />
        </main>
    </div>
</template>
