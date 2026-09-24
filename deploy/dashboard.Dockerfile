# Build do SPA e serviço estático com proxy de /api para a API interna.
FROM node:24-alpine AS build
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
COPY openapi.json /app/openapi.json
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dashboard/dist /srv
