# syntax=docker/dockerfile:1.7
# Multi-stage Next.js build using `output: 'standalone'`.
#   * deps stage installs node_modules
#   * build stage compiles the app
#   * runner stage ships only the standalone bundle + static + public

FROM node:22-alpine AS deps
WORKDIR /app
# .npmrc carries `legacy-peer-deps=true` — next@15.0.x's peer range predates
# React 19 stable, so npm needs that flag to install/ci cleanly.
COPY package.json package-lock.json* .npmrc* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install --no-audit --no-fund; fi

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_* are inlined at build time; the app code also defaults to
# these values so a plain `next build` (no Docker) still works.
ARG NEXT_PUBLIC_API_BASE=/api/v1
ARG NEXT_PUBLIC_WS_BASE=/ws
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_WS_BASE=$NEXT_PUBLIC_WS_BASE
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
