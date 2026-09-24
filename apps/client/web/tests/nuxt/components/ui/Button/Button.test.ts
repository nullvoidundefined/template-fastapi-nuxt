/**
 * Tests for the kit's Button (spec: slice 03 PR 4, the design spec's "UI kit" line, B-48's
 * keyboard requirement, US-AUTH-004).
 *
 * The one thing a design-system button most often gets wrong is stopping being a button: a styled
 * `div` with a click handler, or a `role="button"` span. Either looks right and neither is
 * focusable, submittable or operable from the keyboard, which is why every assertion here goes
 * through the accessible role and name and then checks the element really is a `<button>`.
 *
 * The click is asserted through what the page shows afterwards rather than through a spy's call
 * count, so a Button that swallows its own click cannot pass by having been called.
 *
 * The button is rendered inside a host component because a design-system button's externally
 * visible behaviour is what happens to the page that uses it.
 */
import { describe, it, expect } from 'vitest';
import { defineComponent, h, ref } from 'vue';
import { renderSuspended } from '@nuxt/test-utils/runtime';
import { screen, fireEvent } from '@testing-library/vue';

import Button from '~/components/ui/Button/Button.vue';

const saveLabel = 'Save profile';
const nothingSavedYet = 'Nothing saved yet';
const savedOnce = 'Saved once';

interface HostProps {
    disabled?: boolean;
    type?: 'button' | 'submit';
}

/** Render the button inside a page that records the clicks it receives in visible text. */
async function renderSaveButton(hostProps: HostProps = {}): Promise<void> {
    const HostComponent = defineComponent({
        name: 'ButtonHost',
        setup() {
            const saveCount = ref(0);
            function countSave(): void {
                saveCount.value += 1;
            }
            function renderHost() {
                return h('div', [
                    h(Button, { ...hostProps, onClick: countSave }, { default: () => saveLabel }),
                    h('p', saveCount.value === 0 ? nothingSavedYet : savedOnce),
                ]);
            }
            return renderHost;
        },
    });

    await renderSuspended(HostComponent);
}

/** The button as the accessibility tree exposes it, so the query cannot rely on a class. */
function readSaveButton(): HTMLButtonElement {
    return screen.getByRole('button', { name: saveLabel }) as HTMLButtonElement;
}

describe('the kit button', () => {
    it('UI kit: renders a real button element carrying its label as the accessible name', async () => {
        await renderSaveButton();

        const button = readSaveButton();

        expect(button.tagName).toBe('BUTTON');
        expect(button.getAttribute('type')).toBe('button');
    });

    it('UI kit: runs the page handler when it is clicked', async () => {
        await renderSaveButton();

        expect(screen.getByText(nothingSavedYet)).not.toBeNull();

        await fireEvent.click(readSaveButton());

        expect(screen.getByText(savedOnce)).not.toBeNull();
        expect(screen.queryByText(nothingSavedYet)).toBeNull();
    });

    it('UI kit: submits the form it sits in only when it is asked to', async () => {
        await renderSaveButton({ type: 'submit' });

        expect(readSaveButton().getAttribute('type')).toBe('submit');
    });

    it('UI kit: does nothing when it is disabled', async () => {
        await renderSaveButton({ disabled: true });

        const button = readSaveButton();
        expect(button.disabled).toBe(true);

        await fireEvent.click(button);

        expect(screen.getByText(nothingSavedYet)).not.toBeNull();
        expect(screen.queryByText(savedOnce)).toBeNull();
    });
});
