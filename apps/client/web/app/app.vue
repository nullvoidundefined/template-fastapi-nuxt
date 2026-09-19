<script setup lang="ts">
/**
 * Root component: every route renders inside its layout (the default layout unless a page names another).
 * The title template appends the product name to each page's own title, so every tab is identifiable.
 */
import { useHead } from '#imports';

defineOptions({ name: 'App' });

const productName = 'template-fastapi-nuxt';

/** Return the tab title: "<page> | product", or the product name alone when the page sets none. */
function formatDocumentTitle(pageTitle?: string | null): string {
    if (!pageTitle || pageTitle === productName) {
        return productName;
    }
    return `${pageTitle} | ${productName}`;
}

useHead({ titleTemplate: formatDocumentTitle });
</script>

<template>
    <NuxtLayout>
        <NuxtPage />
    </NuxtLayout>
</template>
