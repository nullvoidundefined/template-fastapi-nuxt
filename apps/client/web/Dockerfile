# Web image (R-351): the Nuxt app built with Nitro's node-server preset, run as the non-root
# `node` user. Build context: the repository root, because the app depends on the workspace
# packages @repo/tokens (built during install by its prepare script) and @repo/api-types.
FROM node:25-alpine AS builder
ENV PNPM_HOME=/pnpm PATH="/pnpm:$PATH"
RUN corepack enable
WORKDIR /repo
# Dependencies first, from the lockfile, so a source edit reuses this layer. package.json comes
# along because its packageManager field pins the pnpm version corepack runs.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm fetch
COPY packages/ packages/
COPY apps/client/web/ apps/client/web/
RUN pnpm install --offline --frozen-lockfile --filter @repo/web...
RUN pnpm --filter @repo/web build

FROM node:25-alpine
WORKDIR /app
ENV NODE_ENV=production HOST=0.0.0.0 PORT=3000
COPY --from=builder --chown=node:node /repo/apps/client/web/.output ./.output
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:' + process.env.PORT + '/api/health').then((response) => process.exit(response.ok ? 0 : 1), () => process.exit(1))"
CMD ["node", ".output/server/index.mjs"]
