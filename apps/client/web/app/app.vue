<script setup lang="ts">
/**
 * Root component: every route renders inside its layout (the default layout unless a page names another).
 * The title template appends the product name to each page's own title, so every tab is identifiable.
 * The theme boot script is inlined at the top of <head> so the stored theme is set on <html> before
 * the first paint (B-37); the server renders no theme attribute itself, since it cannot know one.
 */
import { useHead } from '#imports';

import { buildThemeBootScript } from '~/services/theme/buildThemeBootScript';

defineOptions({ name: 'App' });

const productName = 'template-fastapi-nuxt';

/** Return the tab title: "<page> | product", or the product name alone when the page sets none. */
function formatDocumentTitle(pageTitle?: string | null): string {
    if (!pageTitle || pageTitle === productName) {
        return productName;
    }
    return `${pageTitle} | ${productName}`;
}

useHead({
    titleTemplate: formatDocumentTitle,
    script: [{ key: 'theme-boot', innerHTML: buildThemeBootScript(), tagPosition: 'head' }],
});
</script>

<template>
    <NuxtLayout>
        <NuxtPage />
    </NuxtLayout>
</template>
