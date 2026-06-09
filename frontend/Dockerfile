# Dev-oriented image: runs the Vite dev server (matches docker-compose's 5173).
# Vite reads VITE_* vars from the container environment at serve time, so the
# API base URL can be set via docker-compose without rebuilding.
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
