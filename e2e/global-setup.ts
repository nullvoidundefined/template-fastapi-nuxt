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

import { clearRateLimitCounters } from './rateLimitCounters';

const MIGRATE_SERVICE_NAME = 'migrate';
const MIGRATE_TIMEOUT_MS = 120_000;

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
