# Frontend image: build the SPA, then serve it (and reverse-proxy the API) via nginx.
# VITE_API_BASE_URL="" makes the client use relative paths, so the browser talks to
# this same nginx origin and nginx proxies the API — no CORS, no baked host URL.

# ---- build stage ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV VITE_API_BASE_URL=""
RUN npm run build

# ---- serve stage ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
