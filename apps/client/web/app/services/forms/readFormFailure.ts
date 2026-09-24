/**
 * Splits a failed form submission into what each input shows and what the form shows (spec: B-38).
 *
 * Field errors go beside their input; anything else becomes one form-level message. A failure that
 * is not an `ApiRequestError` (the network, a bug) still produces a message rather than nothing.
 */
import { ApiRequestError } from '~/services/apiClient/apiRequestError';
import type { FormFailure } from '~/types/formFailure';

const UNEXPECTED_FAILURE_MESSAGE = 'Something went wrong. Try again.';

/** Return the per-field messages and the form-level message a failed submission should show. */
export function readFormFailure(failure: unknown): FormFailure {
    if (!(failure instanceof ApiRequestError)) {
        return { fieldMessages: {}, formMessage: UNEXPECTED_FAILURE_MESSAGE };
    }
    const fieldMessages = Object.fromEntries(
        failure.fieldErrors.map(({ field, message }) => [field, message]),
    );
    const hasFieldMessages = Object.keys(fieldMessages).length > 0;
    return { fieldMessages, formMessage: hasFieldMessages ? undefined : failure.message };
}
