/**
 * The error every failed backend call becomes (spec: slice 03 PR 3, "the query layer").
 *
 * It carries the status because the caller's decision depends on it rather than on the message:
 * `requireSession` sends a visitor to the sign-in page on 401 and shows an error on 5xx, and both
 * arrive as the same rejected query. It carries the registry code for the same reason, since the
 * backend documents `error` as prose a client never parses and `code` as the value it switches on.
 * Both are read defensively, because a failure can come from something in front of the backend
 * that answers an HTML page rather than the `{ code, error }` envelope.
 */

const UNKNOWN_FAILURE_MESSAGE = 'The request failed';

type ErrorEnvelope = {
    code?: unknown;
    error?: unknown;
};

export class ApiRequestError extends Error {
    readonly status: number;
    readonly code: string | undefined;

    constructor(status: number, body: unknown) {
        super(readEnvelopeMessage(status, body));
        this.name = 'ApiRequestError';
        this.status = status;
        this.code = readEnvelopeCode(body);
    }
}

/** Return the envelope's prose when the body is one, else a message naming the status. */
function readEnvelopeMessage(status: number, body: unknown): string {
    const envelopeMessage = readEnvelope(body)?.error;
    if (typeof envelopeMessage === 'string' && envelopeMessage !== '') {
        return envelopeMessage;
    }
    return `${UNKNOWN_FAILURE_MESSAGE} with status ${status}`;
}

/** Return the envelope's registry code, or undefined when the body is not the envelope. */
function readEnvelopeCode(body: unknown): string | undefined {
    const envelopeCode = readEnvelope(body)?.code;
    return typeof envelopeCode === 'string' ? envelopeCode : undefined;
}

/** Narrow a failure body to the envelope shape, refusing a string, null, or an array. */
function readEnvelope(body: unknown): ErrorEnvelope | undefined {
    if (typeof body !== 'object' || body === null || Array.isArray(body)) {
        return undefined;
    }
    return body as ErrorEnvelope;
}
