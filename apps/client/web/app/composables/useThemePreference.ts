/**
 * The visitor's theme preference, shared app state (spec: B-37, the Nuxt track's Theme section).
 *
 * Held in `useState` so every caller reads one value. The server always starts at `system` and
 * never renders a theme attribute, because it cannot read localStorage; `plugins/theme.client.ts`
 * loads the stored choice after hydration, persists every change, and applies it to <html>.
 */
import { useState } from '#app';
import type { Ref } from 'vue';

import type { ThemePreference } from '~/types/themePreference';

const THEME_PREFERENCE_STATE_KEY = 'theme-preference';

type ThemePreferenceState = {
    themePreference: Ref<ThemePreference>;
    setThemePreference: (preference: ThemePreference) => void;
};

/** Return the shared preference and the one function that changes it. */
export function useThemePreference(): ThemePreferenceState {
    const themePreference = useState<ThemePreference>(THEME_PREFERENCE_STATE_KEY, () => 'system');

    function setThemePreference(preference: ThemePreference): void {
        themePreference.value = preference;
    }

    return { setThemePreference, themePreference };
}
