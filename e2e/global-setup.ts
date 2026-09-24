/**
 * Playwright global setup: brings the database to head before any spec runs.
 *
 * It invokes the same one-shot compose `migrate` service the stack itself depends on, rather than
 * a second migration path of its own, so there is exactly one way the schema is created and the
 * end-to-end suite cannot pass against a schema that compose would never produce. Running it after
 * compose has already run it is a no-op, because Alembic stops as soon as the chain is at head.
 *
 * Set E2E_SKIP_MIGRATE when the suite is pointed at an environment migrated by its own deploy,
 * where there is no local compose project to run the service in.
 */
import { execFileSync } from 'node:child_process';

const MIGRATE_SERVICE_NAME = 'migrate';
const MIGRATE_TIMEOUT_MS = 120_000;
const RATE_LIMIT_RESET_SCRIPT =
    "for _, key in ipairs(redis.call('KEYS', 'ratelimit:*')) do redis.call('DEL', key) end";

export default function migrateBeforeEndToEndSuite(): void {
    if (process.env.E2E_SKIP_MIGRATE) {
        return;
    }
    // No --no-deps: the service declares `postgres` as a healthy dependency, so compose starts
    // and waits for it. Skipping dependencies only works when the stack is already up, which is
    // true in CI and not true for someone running the suite on its own.
    execFileSync('docker', ['compose', 'run', '--rm', MIGRATE_SERVICE_NAME], {
        stdio: 'inherit',
        timeout: MIGRATE_TIMEOUT_MS,
    });
    clearRateLimitCounters();
}

/**
 * Delete every rate-limit counter in the compose Redis, so the specs' own requests in earlier runs
 * cannot push this run over the auth bucket (IAN-326). The counters persist between runs because
 * the compose Redis does, and the auth bucket allows only ten requests per fifteen minutes.
 */
function clearRateLimitCounters(): void {
    execFileSync(
        'docker',
        ['compose', 'exec', '-T', 'redis', 'redis-cli', 'EVAL', RATE_LIMIT_RESET_SCRIPT, '0'],
        { stdio: 'inherit' },
    );
}
