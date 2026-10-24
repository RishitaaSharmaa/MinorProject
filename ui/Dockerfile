# Build context is the repository root (see docker-compose.yml): the in-browser engine bundles
# the backend's Python source (app/, llm/) into the static site.
FROM node:20-alpine AS build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ .
COPY app /app
COPY llm /llm
RUN npm run build

FROM nginx:1.27-alpine
COPY ui/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 80
