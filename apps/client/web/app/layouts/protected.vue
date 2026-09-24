<script setup lang="ts">
/**
 * Layout for signed-in pages: renders the page only once the session has resolved.
 *
 * Without the guard a protected page paints its content for the moment between the request and
 * the answer, which for a visitor who turns out to be signed out means seeing a page they are not
 * entitled to before being sent away from it.
 *
 * It has no <h1>, because each page owns its one heading.
 */
import { NuxtLink } from '#components';

import ThemeToggle from '~/components/ThemeToggle/ThemeToggle.vue';
import { useSessionQuery } from '~/composables/useSessionQuery';
import { useSignOutMutation } from '~/composables/useSignOutMutation';
import styles from './protected.module.scss';

defineOptions({ name: 'ProtectedLayout' });

const { data: signedInUser, isSuccess: hasSession } = useSessionQuery();
const signOutMutation = useSignOutMutation();

/** End the session, then send the visitor to the page they can still use. */
async function signOutAndLeave(): Promise<void> {
    await signOutMutation.mutateAsync(undefined);
    await navigateTo('/login');
}
</script>

<template>
    <div data-test-id="protected-layout" :class="styles.shell">
        <header :class="styles.header">
            <NuxtLink to="/dashboard" :class="styles.brand">template-fastapi-nuxt</NuxtLink>
            <ThemeToggle />
            <div v-if="hasSession" :class="styles.account">
                <span data-test-id="signed-in-email">{{ signedInUser?.email }}</span>
                <button
                    type="button"
                    data-test-id="sign-out"
                    :class="styles.signOut"
                    :disabled="signOutMutation.isPending.value"
                    @click="signOutAndLeave"
                >
                    Sign out
                </button>
            </div>
        </header>
        <main :class="styles.main">
            <slot v-if="hasSession" />
        </main>
    </div>
</template>
