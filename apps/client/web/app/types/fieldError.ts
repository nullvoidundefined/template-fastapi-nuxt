/** One rejected field, as `INPUT_VALIDATION_ERROR` names it (spec: B-38). */
export type FieldError = {
    field: string;
    message: string;
};
