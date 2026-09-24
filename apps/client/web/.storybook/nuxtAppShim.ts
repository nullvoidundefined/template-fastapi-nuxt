/**
 * Storybook's stand-in for the one `#app` export the ui kit uses (spec: B-39).
 *
 * Storybook renders components without a Nuxt app, so `useState` is backed by a module-level map
 * of refs keyed the same way Nuxt keys them. Each story iframe is its own page, so state never
 * leaks between stories. The installed Nuxt Storybook framework does not support this Storybook
 * major, which is why the kit runs on the plain Vue framework with this alias instead.
 */
import { ref, type Ref } from 'vue';

const statesByKey = new Map<string, Ref<unknown>>();

/** Return the shared ref for this key, initialising it on first use as Nuxt's `useState` does. */
export function useState<T>(key: string, init?: () => T): Ref<T> {
    if (!statesByKey.has(key)) {
        statesByKey.set(key, ref(init ? init() : undefined));
    }
    return statesByKey.get(key) as Ref<T>;
}
