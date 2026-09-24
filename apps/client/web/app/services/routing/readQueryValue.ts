/**
 * Reads one route query value as a string. vue-router types a query value as a string, null, or an
 * array of them when the key repeats, and a page needs one value: the first, or empty when absent.
 */

const ABSENT_VALUE = '';

/** Return the query value as one string, taking the first when the key repeats. */
export function readQueryValue(queryValue: unknown): string {
    const [firstValue] = [queryValue].flat();
    return typeof firstValue === 'string' ? firstValue : ABSENT_VALUE;
}
