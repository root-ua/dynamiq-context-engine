# syntax=docker/dockerfile:1.7
#
# Hocuspocus collab server (Yjs websocket + persistence).

FROM node:22-slim AS base
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
WORKDIR /app

# Dev target — hot-reload via tsx watch.
FROM base AS dev
ENV NODE_ENV=development
COPY package.json ./
RUN pnpm install --no-frozen-lockfile
COPY . .
EXPOSE 1234
CMD ["pnpm", "dev"]

# Production deps only.
FROM base AS deps
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --prod=false --no-frozen-lockfile

# Build compiled JS.
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# Runtime — prod deps + dist only, non-root.
FROM node:22-slim AS runner
ENV NODE_ENV=production
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate \
 && groupadd --system --gid 1001 nodejs \
 && useradd --system --uid 1001 --gid nodejs collab

COPY --chown=collab:nodejs package.json ./
RUN pnpm install --prod --no-frozen-lockfile
COPY --from=builder --chown=collab:nodejs /app/dist ./dist

USER collab
EXPOSE 1234

# Hocuspocus responds 200 on a plain HTTP GET to the WS port before
# upgrading; we use that as liveness (no custom health route needed).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:1234/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "dist/server.js"]
