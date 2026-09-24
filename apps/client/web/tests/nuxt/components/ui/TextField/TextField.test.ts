/**
 * Tests for the kit's TextField (spec: B-38, B-48, US-AUTH-004).
 *
 * B-38 requires a field error beside the input it names. "Beside" is asserted as an accessible
 * association, not as layout: the input is found by its label, and its error is read through
 * `aria-describedby`, so a message rendered nearby but unattached fails.
 */
import { describe, it, expect } from 'vitest';
import { defineComponent, h, ref } from 'vue';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen, fireEvent } from '@testing-library/vue';

import TextField from '~/components/ui/TextField/TextField.vue';

const emailLabel = 'Email';
const emailError = 'Enter a valid email address';

/** Render the field bound to a host value the page echoes, so typing is observable. */
async function renderEmailField(errorMessage?: string): Promise<void> {
    const HostComponent = defineComponent({
        name: 'TextFieldHost',
        setup() {
            const emailValue = ref('');
            return () =>
                h('div', [
                    h(TextField, {
                        errorMessage,
                        label: emailLabel,
                        modelValue: emailValue.value,
                        name: 'email',
                        type: 'email',
                        'onUpdate:modelValue': (nextValue: string) => {
                            emailValue.value = nextValue;
                        },
                    }),
                    h('output', { 'data-test-id': 'echo' }, emailValue.value),
                ]);
        },
    });
    await renderSuspended(HostComponent);
}

describe('TextField', () => {
    it('B-48: labels its input so it is found by accessible name', async () => {
        await renderEmailField();

        const emailInput = screen.getByLabelText(emailLabel);

        expect(emailInput.tagName).toBe('INPUT');
        expect(emailInput.getAttribute('type')).toBe('email');
        expect(emailInput.getAttribute('name')).toBe('email');
    });

    it('B-38: associates its error with the input and marks the input invalid', async () => {
        await renderEmailField(emailError);

        const emailInput = screen.getByLabelText(emailLabel);
        const describedById = emailInput.getAttribute('aria-describedby');

        expect(describedById).toBeTruthy();
        expect(document.getElementById(describedById!)?.textContent).toContain(emailError);
        expect(emailInput.getAttribute('aria-invalid')).toBe('true');
    });

    it('B-38: carries no error association when there is no error', async () => {
        await renderEmailField();

        const emailInput = screen.getByLabelText(emailLabel);

        expect(emailInput.getAttribute('aria-invalid')).not.toBe('true');
        expect(emailInput.getAttribute('aria-describedby')).toBeNull();
    });

    it('updates the bound value as the visitor types', async () => {
        await renderEmailField();

        await fireEvent.update(screen.getByLabelText(emailLabel), 'reader@example.test');

        const echo = document.querySelector('[data-test-id="echo"]');
        expect(echo?.textContent).toBe('reader@example.test');
    });
});
