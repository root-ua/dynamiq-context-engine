# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the Next.js web client.
#
# `dev` target — hot-reload, volume-mounted. Used by docker-compose.
# `runner` target — default, standalone production build. Used by Render
# and any other PaaS via `docker build -t web .` (no --target flag needed).

# ---------------------------------------------------------------------------
# Base: node + pnpm + corepack
# ---------------------------------------------------------------------------
FROM node:22-slim AS base
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
WORKDIR /app

# ---------------------------------------------------------------------------
# Dev target — docker-compose mounts the source tree and runs `pnpm dev`.
# ---------------------------------------------------------------------------
FROM base AS dev
ENV NODE_ENV=development
COPY package.json ./
RUN pnpm install --no-frozen-lockfile
COPY . .
EXPOSE 3000
CMD ["pnpm", "dev"]

# ---------------------------------------------------------------------------
# Deps — install only production deps for a cacheable layer.
# ---------------------------------------------------------------------------
FROM base AS deps
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --prod=false --no-frozen-lockfile

# ---------------------------------------------------------------------------
# Builder — full install, compile .next with standalone output.
# ---------------------------------------------------------------------------
FROM base AS builder
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* env vars are baked at build time. Render sets them via
# the dashboard and re-triggers a build; locally they're passed through
# docker compose build args if needed.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_COLLAB_URL
ARG NEXT_PUBLIC_BETTER_AUTH_URL
ARG NEXT_PUBLIC_SITE_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_COLLAB_URL=${NEXT_PUBLIC_COLLAB_URL} \
    NEXT_PUBLIC_BETTER_AUTH_URL=${NEXT_PUBLIC_BETTER_AUTH_URL} \
    NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
RUN pnpm build

# ---------------------------------------------------------------------------
# Runner — slim runtime, non-root user, just the standalone artifact.
# ---------------------------------------------------------------------------
FROM node:22-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app

# Non-root user.
RUN groupadd --system --gid 1001 nodejs \
 && useradd --system --uid 1001 --gid nodejs nextjs

# Copy the public/ and standalone build tree. Next.js ships its own
# server.js in .next/standalone that serves API routes + RSC + static.
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
