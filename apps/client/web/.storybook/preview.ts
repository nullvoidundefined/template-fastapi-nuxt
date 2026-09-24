/**
 * The decorators and parameters every story renders under.
 *
 * The token stylesheet is imported here rather than per story, because a component styled against
 * custom properties that are not defined renders with the browser's fallbacks and the snapshot
 * then pins a rendering nobody intended.
 */
import type { Preview } from '@storybook/vue3-vite';

import '../app/assets/css/main.scss';

const preview: Preview = {
    parameters: {
        a11y: { test: 'error' },
        controls: { matchers: { color: /(background|color)$/i, date: /Date$/i } },
    },
};

export default preview;
