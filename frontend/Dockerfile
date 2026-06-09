FROM node:20-alpine

WORKDIR /app

ARG NEXT_PUBLIC_API_URL
ARG API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV API_URL=${API_URL}

COPY . .

RUN if [ -f /app/frontend/package.json ]; then cp -R /app/frontend/. /app/; fi \
 && if [ ! -f /app/package.json ]; then echo "package.json not found. Set Root Directory to frontend or use repo-root context with frontend/Dockerfile."; exit 1; fi \
 && npm ci --legacy-peer-deps \
 && npm run build

RUN chmod +x /app/docker-entrypoint.sh \
 && chown -R node:node /app

USER node

EXPOSE 3000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
