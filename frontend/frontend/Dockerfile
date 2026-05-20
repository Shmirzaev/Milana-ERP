FROM node:20-alpine

WORKDIR /app

COPY . .

RUN if [ ! -f /app/package.json ]; then echo "package.json not found in frontend rootDir build context."; exit 1; fi \
 && npm ci --legacy-peer-deps \
 && npm run build

RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
