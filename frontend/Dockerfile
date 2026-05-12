FROM node:20-alpine

WORKDIR /app

COPY . .

RUN if [ -f /app/frontend/package.json ]; then cp -R /app/frontend/. /app/; fi \
 && if [ ! -f /app/package.json ]; then echo "package.json not found. Set Root Directory to frontend or use repo-root context with frontend/Dockerfile."; exit 1; fi \
 && npm ci --legacy-peer-deps \
 && npm run build

EXPOSE 3000

CMD ["sh", "-c", "npm run start -- -p ${PORT:-3000}"]
