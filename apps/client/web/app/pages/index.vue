<!-- Landing page (US-LANDING-001, spec B-49): names the product in the page's only <h1> and links to log in and register. -->
<template>
    <section data-test-id="landing-page" :class="$style.landing">
        <h1 :class="$style.title">template-fastapi-nuxt</h1>
        <p :class="$style.lead">A FastAPI and Nuxt starting point for new applications.</p>
        <nav aria-label="Account" :class="$style.actions">
            <NuxtLink to="/login" :class="$style.primaryAction">Log in</NuxtLink>
            <NuxtLink to="/register" :class="$style.secondaryAction">Register</NuxtLink>
        </nav>
    </section>
</template>

<style module lang="scss">
.landing {
    max-width: 640px;
    margin: 0 auto;
    text-align: center;
}

.title {
    font-size: var(--font-size-hero);
    font-weight: var(--font-weight-black);
    letter-spacing: var(--letter-spacing-hero);
    line-height: var(--line-height-hero);
}

.lead {
    margin-top: var(--spacing-4);
    font-size: var(--font-size-subtitle);
    line-height: var(--line-height-paragraph);
    color: var(--foreground-muted);
}

.actions {
    display: flex;
    justify-content: center;
    gap: var(--spacing-3);
    margin-top: var(--spacing-8);
}

.primaryAction,
.secondaryAction {
    padding: var(--spacing-3) var(--spacing-6);
    border-radius: var(--radius-button);
    font-size: var(--font-size-label);
    font-weight: var(--font-weight-semibold);
    text-decoration: none;
    transition: background var(--transition-hover);
}

.primaryAction {
    background: var(--accent);
    color: var(--white);

    &:hover {
        background: var(--accent-hover);
    }
}

.secondaryAction {
    background: var(--surface);
    color: var(--foreground);

    &:hover {
        background: var(--surface-hover);
    }
}

@media (max-width: 640px) {
    .title {
        font-size: var(--font-size-hero-mobile);
    }
}
</style>
