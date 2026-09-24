#!/usr/bin/env bash
# Regenerate the visual-regression baselines (spec: B-39) inside the same Playwright image CI uses,
# because a baseline rendered on macOS differs from a Linux render on every font edge. The repo is
# copied into the container without node_modules, so the host's native modules are never replaced.
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/.." && pwd)
snapshot_dir="$repo_root/e2e/visual/__snapshots__"
playwright_image="mcr.microsoft.com/playwright:v1.63.0-noble"
mkdir -p "$snapshot_dir"

docker run --rm \
    -v "$repo_root":/src:ro \
    -v "$snapshot_dir":/out \
    "$playwright_image" \
    bash -c '
        set -euo pipefail
        mkdir /work
        tar --exclude=node_modules --exclude=.git --exclude=.nuxt --exclude=.output \
            -C /src -cf - . | tar -C /work -xf -
        cd /work
        corepack enable
        CI=true pnpm install --frozen-lockfile
        rm -rf e2e/visual/__snapshots__
        pnpm exec playwright test --config playwright.visual.config.ts --update-snapshots
        rm -rf /out/*
        cp e2e/visual/__snapshots__/* /out/
    '
