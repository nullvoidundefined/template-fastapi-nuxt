// ESLint flat config: Nuxt's generated Vue and TypeScript rules plus the Vue track's own rules
// (block order, macro order, v-html ban) and the vuejs-accessibility recommended set.
import vueAccessibility from 'eslint-plugin-vuejs-accessibility';

import withNuxt from './.nuxt/eslint.config.mjs';

export default withNuxt(...vueAccessibility.configs['flat/recommended'], {
    files: ['**/*.vue'],
    rules: {
        'vue/block-order': ['error', { order: ['script', 'template'] }],
        'vue/define-macros-order': [
            'error',
            { order: ['defineOptions', 'defineProps', 'defineEmits', 'defineSlots'] },
        ],
        'vue/no-v-html': 'error',
    },
});
