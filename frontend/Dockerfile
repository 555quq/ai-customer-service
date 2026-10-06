ARG NODE_IMAGE=node:20.19.4-alpine3.22@sha256:df02558528d3d3d0d621f112e232611aecfee7cbc654f6b375765f72bb262799
ARG NGINX_IMAGE=nginx:1.29.1-alpine3.22@sha256:42a516af16b852e33b7682d5ef8acbd5d13fe08fecadc7ed98605ba5e3b26ab8
FROM ${NODE_IMAGE} AS builder

WORKDIR /workspace
RUN corepack enable && corepack prepare pnpm@10.34.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json tsconfig*.json ./
COPY packages/shared/package.json packages/shared/package.json
COPY apps/admin/package.json apps/admin/package.json
COPY apps/agent/package.json apps/agent/package.json
COPY apps/widget/package.json apps/widget/package.json
RUN pnpm install --frozen-lockfile
COPY . .

ARG APP
ARG VITE_BRIDGE_API_BASE=
ENV VITE_BRIDGE_API_BASE=${VITE_BRIDGE_API_BASE}
RUN pnpm --filter "@ai-cs/${APP}" build && \
    mkdir -p /out && cp -R "apps/${APP}/dist/." /out/ && \
    if [ "${APP}" = "admin" ]; then \
      pnpm --filter @ai-cs/widget build && mkdir -p /out/assets && cp apps/widget/dist/widget.js /out/assets/widget.js; \
    fi

FROM ${NGINX_IMAGE}

COPY nginx-spa.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /out/ /usr/share/nginx/html/
EXPOSE 8080
