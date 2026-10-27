FROM node:22.23.4-alpine3.24 AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine3.24
# CVE-2026-111497: require the patched Alpine Brotli decoder.
RUN apk add --no-cache --upgrade 'brotli-libs>=1.2.1-r0'
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
