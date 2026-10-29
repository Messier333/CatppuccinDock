FROM node:26.12.1-alpine3.24 AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine3.24
# Require the patched Alpine Brotli decoder and curl runtime packages.
RUN apk add --no-cache --upgrade \
    'brotli-libs>=1.2.1-r0' \
    'curl>=8.23.0-r0'
COPY nginx-main.conf /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

USER nginx

# Skip the root-oriented image entrypoint. All writable nginx paths live in /tmp.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
