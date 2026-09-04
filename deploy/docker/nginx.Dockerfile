# nginx + built Vue frontend, baked into one image so the frontend never
# depends on a shared volume being populated in the right order (unlike
# Django's collected `static/`, which nginx reads from `static_volume`,
# a genuinely runtime artifact — see docker-compose.yml).
#
# Build context is the repo root (same as django.Dockerfile).
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/dist /usr/share/nginx/html
