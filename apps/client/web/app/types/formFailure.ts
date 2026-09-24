/** What a failed form submission shows: a message per field, and one for the form itself. */
export type FormFailure = {
    fieldMessages: Record<string, string>;
    formMessage: string | undefined;
};
