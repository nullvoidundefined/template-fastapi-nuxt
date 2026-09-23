/**
 * Test harness for `app/plugins/queryClient.ts`, shared by the client and server plugin tests.
 *
 * A Nuxt plugin runs once per Nuxt app instance, which on the server means once per request, so the
 * only way to tell a per-request `QueryClient` from a module-level one is to run the same plugin
 * against two Nuxt app instances and compare what each installed. The harness therefore builds a
 * stand-in Nuxt app carrying the two things the plugin uses, a real Vue app and a hook registry,
 * and reads the installed client back out of the Vue app through vue-query's own `useQueryClient`,
 * so the test observes what a component would resolve rather than what the plugin was handed.
 *
 * The plugin still runs inside the real test Nuxt app's context, because `useState` resolves the
 * ambient Nuxt app rather than the one passed as an argument, and the dehydrated payload has to
 * land where a page would read it.
 */
import { createApp, defineComponent, h, type App } from 'vue';
import { useQueryClient, type QueryClient } from '@tanstack/vue-query';
import { useNuxtApp, type NuxtApp } from '#app';

type HookHandler = () => unknown;

export type StubNuxtApp = {
    /** The stand-in Nuxt app handed to the plugin. */
    nuxtApp: NuxtApp;
    /** The Vue app the plugin installs vue-query into. */
    vueApp: App;
    /** Fire every handler the plugin registered for the named Nuxt hook. */
    callHook: (hookName: string) => Promise<void>;
};

/** Build one stand-in Nuxt app, the way Nuxt builds one per request. */
export function createStubNuxtApp(): StubNuxtApp {
    const handlersByHookName = new Map<string, HookHandler[]>();
    const vueApp = createApp(defineComponent({ name: 'PluginHost', render: () => h('div') }));

    function hook(hookName: string, handler: HookHandler): () => void {
        const registeredHandlers = handlersByHookName.get(hookName) ?? [];
        registeredHandlers.push(handler);
        handlersByHookName.set(hookName, registeredHandlers);
        return () => handlersByHookName.delete(hookName);
    }

    async function callHook(hookName: string): Promise<void> {
        for (const registeredHandler of handlersByHookName.get(hookName) ?? []) {
            await registeredHandler();
        }
    }

    const nuxtApp = {
        vueApp,
        hooks: { hook, hookOnce: hook, callHook },
        hook,
        callHook,
        payload: { state: {} },
    } as unknown as NuxtApp;

    return { nuxtApp, vueApp, callHook };
}

/** Run the plugin against the stand-in app, accepting the function and the object plugin forms. */
export async function runQueryClientPlugin(
    queryClientPlugin: unknown,
    stubNuxtApp: StubNuxtApp,
): Promise<void> {
    const pluginSetup = readPluginSetup(queryClientPlugin);
    await useNuxtApp().runWithContext(() => pluginSetup(stubNuxtApp.nuxtApp));
}

/** Return the client a component would resolve from the Vue app the plugin installed into. */
export function readInstalledQueryClient(vueApp: App): QueryClient {
    return vueApp.runWithContext(() => useQueryClient());
}

/** Find the callable part of a Nuxt plugin, whichever of the two forms it was defined with. */
function readPluginSetup(queryClientPlugin: unknown): (nuxtApp: NuxtApp) => unknown {
    if (typeof queryClientPlugin === 'function') {
        return queryClientPlugin as (nuxtApp: NuxtApp) => unknown;
    }
    const objectPluginSetup = (queryClientPlugin as { setup?: unknown } | null)?.setup;
    if (typeof objectPluginSetup === 'function') {
        return objectPluginSetup as (nuxtApp: NuxtApp) => unknown;
    }
    throw new Error(
        'app/plugins/queryClient.ts must default-export a Nuxt plugin: either defineNuxtPlugin(setup) or defineNuxtPlugin({ setup })',
    );
}
