<script setup lang="ts">
/**
 * Theme toggle: a labelled native select over the three preferences (spec: B-37).
 *
 * A native select is keyboard-operable and announced by its label with no ARIA of its own, which
 * is the whole accessibility contract for a three-way choice in a header.
 */
import { computed, useId } from 'vue';

import { THEME_PREFERENCES } from '~/constants/theme';
import { useThemePreference } from '~/composables/useThemePreference';
import type { ThemePreference } from '~/types/themePreference';
import styles from './ThemeToggle.module.scss';

defineOptions({ name: 'ThemeToggle' });

const themeLabels: Record<ThemePreference, string> = {
    dark: 'Dark',
    light: 'Light',
    system: 'System',
};

const selectId = useId();
const { themePreference, setThemePreference } = useThemePreference();
const selectedPreference = computed({
    get: () => themePreference.value,
    set: (preference: ThemePreference) => setThemePreference(preference),
});
</script>

<template>
    <label :for="selectId" :class="styles.toggle">
        <span>Theme</span>
        <select
            :id="selectId"
            v-model="selectedPreference"
            data-test-id="theme-toggle"
            :class="styles.select"
        >
            <option v-for="preference in THEME_PREFERENCES" :key="preference" :value="preference">
                {{ themeLabels[preference] }}
            </option>
        </select>
    </label>
</template>
