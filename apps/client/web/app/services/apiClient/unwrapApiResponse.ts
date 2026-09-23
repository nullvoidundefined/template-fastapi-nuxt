/**
 * Turns openapi-fetch's return into a value or a throw (spec: slice 03 PR 3, "the query layer").
 *
 * openapi-fetch never throws on an HTTP error. It resolves with `{ data, error, response }`, and a
 * query whose function resolves is a successful query, so without this helper a 401 would reach a
 * component as data and a signed-out visitor would render the dashboard.
 *
 * The decision is made on `response.ok` rather than on the presence of `error` or of `data`,
 * because neither is reliable: a 204 succeeds carrying no body at all, and a failure from a proxy
 * in front of the backend arrives as an HTML string rather than as the `{ code, error }` envelope.
 */
import { ApiRequestError } from '~/services/apiClient/apiRequestError';

type ApiResult<TData> = {
    data?: TData;
    error?: unknown;
    response: Response;
};

/** Return the response's data, or throw the failure the status and body describe. */
export function unwrapApiResponse<TData>({ data, error, response }: ApiResult<TData>): TData {
    const { ok, status } = response;
    if (!ok) {
        throw new ApiRequestError(status, error);
    }
    // openapi-fetch types `data` as optional because one shape carries both branches. Past the
    // check above the route's declared body is what came back, and a 204 declares none.
    return data as TData;
}
