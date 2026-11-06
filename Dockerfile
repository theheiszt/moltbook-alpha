# Build stage for React Vite application
FROM node:24-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm install --legacy-peer-deps

COPY . .
RUN npm run build

# Production runtime stage for Google Cloud Server / Cloud Run
FROM node:24-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=8080

COPY package*.json ./
COPY --from=builder /app/node_modules ./node_modules

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/public ./public
COPY server.ts ./
COPY src/ ./src
COPY firestore.rules ./
COPY firebase.json ./
COPY firebase-applet-config.json ./

EXPOSE 8080

CMD ["node", "node_modules/tsx/dist/cli.mjs", "server.ts"]
