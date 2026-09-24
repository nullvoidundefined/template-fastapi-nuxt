/**
 * Clears the rate-limit counters in the compose Redis (IAN-326).
 *
 * The auth bucket allows ten requests per fifteen minutes per client, every browser spec reaches
 * the stack from the same host address, and the counters persist between runs. Each spec that
 * spends the auth bucket clears it first, so no run depends on how many requests other specs or
 * earlier runs spent. Clearing only ever lowers a count, so a concurrent spec is never pushed over.
 */
import { execFileSync } from 'node:child_process';

const RATE_LIMIT_RESET_SCRIPT =
    "for _, key in ipairs(redis.call('KEYS', 'ratelimit:*')) do redis.call('DEL', key) end";

/** Delete every rate-limit counter; a no-op when the suite targets a deployed environment. */
export function clearRateLimitCounters(): void {
    if (process.env.E2E_SKIP_MIGRATE) {
        return;
    }
    execFileSync(
        'docker',
        ['compose', 'exec', '-T', 'redis', 'redis-cli', 'EVAL', RATE_LIMIT_RESET_SCRIPT, '0'],
        {
            stdio: 'ignore',
        },
    );
}
