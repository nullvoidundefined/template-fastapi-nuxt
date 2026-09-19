<!-- Default layout: the site header and the main landmark every page renders into. It has no <h1>; each page owns its one heading. -->
<template>
    <div :class="$style.shell">
        <header :class="$style.header">
            <NuxtLink to="/" :class="$style.brand">template-fastapi-nuxt</NuxtLink>
        </header>
        <main :class="$style.main">
            <slot />
        </main>
    </div>
</template>

<style module lang="scss">
.shell {
    min-height: 100vh;
    background: var(--background);
    color: var(--foreground);
}

.header {
    display: flex;
    align-items: center;
    padding: var(--spacing-4) var(--spacing-6);
    border-bottom: 1px solid var(--border);
}

.brand {
    font-size: var(--font-size-nav-logo);
    font-weight: var(--font-weight-bold);
    color: var(--foreground);
    text-decoration: none;
}

.main {
    padding: var(--spacing-10) var(--spacing-6);
}
</style>
